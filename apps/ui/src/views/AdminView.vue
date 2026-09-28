<template>
  <div class="screen-body admin-screen">
    <!-- Secret gate: the panel needs the deployment-wide admin secret -->
    <div v-if="!settings.hasAdminSecret && !session.isAdmin" class="card secret-gate">
      <div class="card-header">
        <div>
          <div class="card-title">{{ t('admin.title') }}</div>
          <div class="card-sub">{{ t('admin.secretSub') }}</div>
        </div>
      </div>
      <div class="secret-form">
        <input
          v-model="secretInput"
          type="password"
          class="form-input"
          :placeholder="t('admin.secretPlaceholder')"
          @keyup.enter="applySecret"
        />
        <button class="btn btn-primary" :disabled="!secretInput.trim()" @click="applySecret">
          {{ t('admin.secretApply') }}
        </button>
      </div>
      <div class="secret-hint">{{ t('admin.secretHint') }}</div>
    </div>

    <template v-else>
      <div class="admin-toolbar">
        <div class="admin-tabs" role="tablist">
          <button
            v-for="tab in tabs"
            :key="tab.id"
            type="button"
            role="tab"
            :class="['admin-tab', { active: activeTab === tab.id }]"
            :aria-selected="activeTab === tab.id"
            @click="activeTab = tab.id"
          >
            {{ t(tab.labelKey) }}
          </button>
        </div>
        <button class="btn btn-ghost btn-sm" :disabled="loading" @click="refresh">
          <div v-if="loading" class="spinner"></div>
          <AppIcon v-else name="refresh" :size="13" />
        </button>
        <span
          v-if="!session.isAdmin"
          class="secret-pill"
          :class="{ invalid: settings.isAdminInvalid }"
        >
          {{ settings.isAdminInvalid ? t('admin.invalidSecret') : `admin: ${settings.adminMasked}` }}
        </span>
      </div>

      <div v-if="error" class="admin-error">{{ error }}</div>

      <!-- ── Overview ─────────────────────────────────────────────── -->
      <template v-if="activeTab === 'overview'">
        <div v-if="overview" class="stats-grid">
          <div v-for="s in overviewCards" :key="s.label" class="stat-card">
            <div class="stat-label">{{ s.label }}</div>
            <div class="stat-value">{{ s.value }}</div>
            <div v-if="s.sub" class="stat-sub">{{ s.sub }}</div>
          </div>
        </div>

        <div v-if="queryTrend.length" class="card">
          <div class="card-header">
            <div>
              <div class="card-title">{{ t('admin.queryTrend') }}</div>
              <div class="card-sub">{{ t('admin.queryTrendSub') }}</div>
            </div>
            <div class="trend-legend">
              <span><i class="legend-swatch queries"></i>{{ t('admin.queries') }}</span>
              <span><i class="legend-swatch errors"></i>{{ t('admin.errors') }}</span>
            </div>
          </div>
          <div class="query-bars">
            <div v-for="day in queryTrend" :key="day.day" class="query-bar-col" :title="`${day.day}: ${day.count} (${day.errors})`">
              <div class="query-bar errors" :style="{ height: day.errorsHeight + '%' }"></div>
              <div class="query-bar queries" :style="{ height: day.countHeight + '%' }"></div>
              <div class="query-bar-label">{{ day.dayLabel }}</div>
            </div>
          </div>
        </div>

        <div v-if="tenants.length" class="card">
          <div class="card-header">
            <div class="card-title">{{ t('admin.tenantsTitle') }}</div>
            <span class="badge badge-muted">{{ tenants.length }}</span>
          </div>
          <table>
            <thead>
              <tr>
                <th>{{ t('admin.tenant') }}</th>
                <th>{{ t('admin.users') }}</th>
                <th>{{ t('admin.documents') }}</th>
                <th>{{ t('admin.chunks') }}</th>
                <th>{{ t('admin.sessions') }}</th>
                <th>{{ t('admin.queries7d') }}</th>
                <th>{{ t('admin.lastQuery') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="tenant in tenants" :key="tenant.tenant_id">
                <td class="td-mono">{{ tenant.tenant_id }}</td>
                <td class="td-mono">{{ tenant.users }}</td>
                <td class="td-mono">{{ tenant.documents }}</td>
                <td class="td-mono">{{ tenant.chunks }}</td>
                <td class="td-mono">{{ tenant.sessions }}</td>
                <td class="td-mono">{{ tenant.queries_7d }}</td>
                <td class="td-mono">{{ fmtDateTime(tenant.last_query_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- ── Prompts ──────────────────────────────────────────────── -->
      <template v-if="activeTab === 'prompts'">
        <div class="card">
          <div class="card-header">
            <div class="card-title">{{ t('admin.promptsTitle') }}</div>
            <span v-if="prompts" class="badge badge-muted">{{ prompts.total }}</span>
          </div>
          <div class="prompt-filters">
            <input
              v-model="filters.q"
              class="form-input filter-input"
              :placeholder="t('admin.searchPlaceholder')"
              @keyup.enter="promptsOffset = 0; loadPrompts()"
            />
            <input
              v-model="filters.tenantId"
              class="form-input filter-input filter-narrow"
              :placeholder="t('admin.tenant')"
              @keyup.enter="promptsOffset = 0; loadPrompts()"
            />
            <select v-model="filters.mode" class="form-input filter-select" @change="promptsOffset = 0; loadPrompts()">
              <option value="">{{ t('admin.allModes') }}</option>
              <option v-for="mode in PROMPT_MODES" :key="mode" :value="mode">{{ mode }}</option>
            </select>
            <select v-model="filters.status" class="form-input filter-select" @change="promptsOffset = 0; loadPrompts()">
              <option value="">{{ t('admin.allStatuses') }}</option>
              <option v-for="status in PROMPT_STATUSES" :key="status" :value="status">{{ status }}</option>
            </select>
            <select v-model="filters.days" class="form-input filter-select" @change="promptsOffset = 0; loadPrompts()">
              <option v-for="d in [7, 30, 90, 365]" :key="d" :value="d">{{ t('admin.lastDays', { days: d }) }}</option>
            </select>
            <button class="btn btn-primary btn-sm" @click="promptsOffset = 0; loadPrompts()">
              {{ t('common.refresh') }}
            </button>
          </div>

          <div v-if="prompts && !prompts.items.length" class="empty compact-empty">
            <div class="empty-title">{{ t('admin.noPrompts') }}</div>
            <div class="empty-sub">{{ t('admin.noPromptsSub') }}</div>
          </div>
          <table v-if="prompts && prompts.items.length">
            <thead>
              <tr>
                <th>{{ t('admin.time') }}</th>
                <th>{{ t('admin.tenant') }}</th>
                <th>{{ t('admin.user') }}</th>
                <th>{{ t('admin.mode') }}</th>
                <th>{{ t('admin.status') }}</th>
                <th class="col-query">{{ t('admin.prompt') }}</th>
                <th>{{ t('admin.latency') }}</th>
                <th>{{ t('admin.cost') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in prompts.items"
                :key="item.id"
                class="prompt-row"
                @click="openPrompt(item.id)"
              >
                <td class="td-mono">{{ fmtDateTime(item.created_at) }}</td>
                <td class="td-mono">{{ item.tenant_id }}</td>
                <td>{{ promptActor(item, settings.locale) }}</td>
                <td><span class="tag">{{ item.mode }}</span></td>
                <td>
                  <span :class="['badge', statusBadge(item.status)]">{{ item.status }}</span>
                </td>
                <td class="prompt-cell" :title="item.query">{{ item.query }}</td>
                <td class="td-mono">{{ fmtMs(item.latency_ms) }}</td>
                <td class="td-mono">{{ item.cost_usd == null ? '—' : fmtCost(item.cost_usd) }}</td>
              </tr>
            </tbody>
          </table>

          <div v-if="prompts && prompts.total > prompts.limit" class="pager">
            <button class="btn btn-ghost btn-sm" :disabled="promptsOffset === 0" @click="promptsOffset -= prompts.limit; loadPrompts()">
              ←
            </button>
            <span class="pager-label">
              {{ promptsOffset + 1 }}–{{ Math.min(promptsOffset + prompts.limit, prompts.total) }} / {{ prompts.total }}
            </span>
            <button
              class="btn btn-ghost btn-sm"
              :disabled="promptsOffset + prompts.limit >= prompts.total"
              @click="promptsOffset += prompts.limit; loadPrompts()"
            >
              →
            </button>
          </div>
        </div>
      </template>

      <!-- ── Users ────────────────────────────────────────────────── -->
      <template v-if="activeTab === 'users'">
        <div class="card">
          <div class="card-header">
            <div class="card-title">{{ t('admin.usersTitle') }}</div>
            <div class="keys-header-actions">
              <span v-if="users" class="badge badge-muted">{{ users.length }}</span>
              <button class="btn btn-primary btn-sm" @click="userFormOpen = true">
                {{ t('admin.addUser') }}
              </button>
            </div>
          </div>
          <div v-if="users && !users.length" class="empty compact-empty">
            <div class="empty-title">{{ t('admin.noUsers') }}</div>
          </div>
          <table v-if="users && users.length">
            <thead>
              <tr>
                <th>{{ t('admin.user') }}</th>
                <th>{{ t('login.email') }}</th>
                <th>{{ t('admin.tenant') }}</th>
                <th>{{ t('admin.role') }}</th>
                <th>{{ t('admin.keys') }}</th>
                <th>{{ t('admin.queriesTotal') }}</th>
                <th>{{ t('admin.queries7d') }}</th>
                <th>{{ t('admin.lastQuery') }}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="user in users" :key="user.id">
                <td class="file-name">{{ user.name }}</td>
                <td class="td-mono">{{ user.email || '—' }}</td>
                <td class="td-mono">{{ user.tenant_id }}</td>
                <td>
                  <span :class="['badge', user.role === 'admin' ? 'badge-purple' : 'badge-blue']">
                    {{ user.role }}
                  </span>
                </td>
                <td class="td-mono">{{ user.active_keys }}/{{ user.keys }}</td>
                <td class="td-mono">{{ user.queries_total }}</td>
                <td class="td-mono">{{ user.queries_7d }}</td>
                <td class="td-mono">{{ fmtDateTime(user.last_query_at) }}</td>
                <td>
                  <button class="btn btn-ghost btn-sm" @click="openCreateKey(user)">
                    {{ t('admin.issueKey') }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- ── Keys ─────────────────────────────────────────────────── -->
      <template v-if="activeTab === 'keys'">
        <div class="card">
          <div class="card-header">
            <div class="card-title">{{ t('admin.keysTitle') }}</div>
            <div class="keys-header-actions">
              <label class="revoked-toggle">
                <input type="checkbox" v-model="showRevokedKeys" />
                <span>{{ t('admin.showRevoked') }}</span>
              </label>
              <span v-if="keys" class="badge badge-muted">{{ visibleKeys.length }}</span>
              <button class="btn btn-primary btn-sm" @click="openCreateKey()">
                {{ t('admin.createKey') }}
              </button>
            </div>
          </div>

          <div v-if="keys && !visibleKeys.length" class="empty compact-empty">
            <div class="empty-title">{{ t('admin.noKeys') }}</div>
            <div class="empty-sub">{{ t('admin.noKeysSub') }}</div>
          </div>
          <table v-if="keys && visibleKeys.length">
            <thead>
              <tr>
                <th>{{ t('admin.keyName') }}</th>
                <th>{{ t('admin.tenant') }}</th>
                <th>{{ t('admin.user') }}</th>
                <th>{{ t('admin.keyStatus') }}</th>
                <th>{{ t('admin.queriesTotal') }}</th>
                <th>{{ t('admin.queries7d') }}</th>
                <th>{{ t('admin.lastUsed') }}</th>
                <th>{{ t('admin.lastQuery') }}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="key in visibleKeys" :key="key.id">
                <td class="file-name">{{ keyDisplayName(key) }}</td>
                <td class="td-mono">{{ key.tenant_id }}</td>
                <td>{{ keyUserLabel(key, settings.locale) }}</td>
                <td>
                  <span :class="['badge', key.is_active ? 'badge-green' : 'badge-red']">
                    {{ key.is_active ? t('admin.keyActive') : t('admin.keyRevoked') }}
                  </span>
                </td>
                <td class="td-mono">{{ key.queries_total }}</td>
                <td class="td-mono">{{ key.queries_7d }}</td>
                <td class="td-mono">{{ fmtDateTime(key.last_used_at) }}</td>
                <td class="td-mono">{{ fmtDateTime(key.last_query_at) }}</td>
                <td>
                  <button
                    v-if="key.is_active"
                    class="btn btn-danger btn-sm"
                    @click="revokeTarget = key"
                  >
                    {{ t('admin.revoke') }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- Add user modal -->
      <div v-if="userFormOpen" class="modal-overlay" @click.self="userFormOpen = false">
        <div class="modal key-modal">
          <div class="modal-title">{{ t('admin.addUser') }}</div>
          <div class="modal-sub">{{ t('admin.addUserSub') }}</div>
          <div class="form-group">
            <label class="form-label">{{ t('login.email') }}</label>
            <input v-model="userForm.email" type="email" class="form-input" placeholder="name@example.com" />
          </div>
          <div class="form-group">
            <label class="form-label">{{ t('admin.keyName') }}</label>
            <input v-model="userForm.name" class="form-input" :placeholder="t('login.namePlaceholder')" />
          </div>
          <div class="form-group">
            <label class="form-label">{{ t('login.password') }}</label>
            <input v-model="userForm.password" type="password" class="form-input" :placeholder="t('login.passwordPlaceholder')" />
          </div>
          <div class="form-group">
            <label class="form-label">{{ t('admin.role') }}</label>
            <select v-model="userForm.role" class="form-input">
              <option value="member">member</option>
              <option value="admin">admin</option>
            </select>
          </div>
          <div v-if="userFormError" class="admin-error">{{ userFormError }}</div>
          <div class="form-actions">
            <button class="btn btn-ghost" :disabled="userSaving" @click="userFormOpen = false">
              {{ t('common.cancel') }}
            </button>
            <button
              class="btn btn-primary"
              :disabled="userSaving || !userForm.email.trim() || userForm.password.length < 8"
              @click="saveUser"
            >
              {{ userSaving ? t('settings.validating') : t('common.create') }}
            </button>
          </div>
        </div>
      </div>

      <!-- ── LLM provider keys ────────────────────────────────────── -->
      <template v-if="activeTab === 'llm'">
        <div class="card">
          <div class="card-header">
            <div class="card-title">{{ t('admin.llmKeysTitle') }}</div>
            <div class="keys-header-actions">
              <span v-if="llmKeys" class="badge badge-muted">{{ llmKeys.length }}</span>
              <button class="btn btn-primary btn-sm" @click="llmFormOpen = true">
                {{ t('admin.addLlmKey') }}
              </button>
            </div>
          </div>

          <div v-if="llmKeys && !llmKeys.length" class="empty compact-empty">
            <div class="empty-title">{{ t('admin.noLlmKeys') }}</div>
            <div class="empty-sub">{{ t('admin.noLlmKeysSub') }}</div>
          </div>
          <table v-if="llmKeys && llmKeys.length">
            <thead>
              <tr>
                <th>{{ t('admin.provider') }}</th>
                <th>{{ t('admin.keyName') }}</th>
                <th>{{ t('admin.keyValue') }}</th>
                <th>{{ t('admin.keyStatus') }}</th>
                <th>{{ t('admin.requests') }}</th>
                <th>{{ t('admin.lastUsed') }}</th>
                <th>{{ t('admin.created') }}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="key in llmKeys" :key="key.id">
                <td><span class="tag">{{ key.provider }}</span></td>
                <td class="file-name">{{ key.name }}</td>
                <td class="td-mono">{{ key.key_preview }}</td>
                <td>
                  <span :class="['badge', key.is_active ? 'badge-green' : 'badge-muted']">
                    {{ key.is_active ? t('admin.keyActive') : t('admin.rotatedOut') }}
                  </span>
                </td>
                <td class="td-mono">{{ key.requests_count }}</td>
                <td class="td-mono">{{ fmtDateTime(key.last_used_at) }}</td>
                <td class="td-mono">{{ fmtDateTime(key.created_at) }}</td>
                <td>
                  <button class="btn btn-danger btn-sm" @click="deleteLlmKey(key)">
                    {{ llmDeleteTarget?.id === key.id ? t('admin.confirmDelete') : t('common.delete') }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="llmFormOpen" class="modal-overlay" @click.self="llmFormOpen = false">
          <div class="modal key-modal">
            <div class="modal-title">{{ t('admin.addLlmKey') }}</div>
            <div class="modal-sub">{{ t('admin.addLlmKeySub') }}</div>
            <div class="form-group">
              <label class="form-label">{{ t('admin.provider') }}</label>
              <select v-model="llmForm.provider" class="form-input">
                <option value="moonshot">moonshot (Kimi)</option>
                <option value="deepseek">deepseek</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">{{ t('admin.keyName') }}</label>
              <input v-model="llmForm.name" class="form-input" :placeholder="t('admin.keyNamePlaceholder')" />
            </div>
            <div class="form-group">
              <label class="form-label">{{ t('admin.keyValue') }}</label>
              <input v-model="llmForm.key" type="password" class="form-input" placeholder="sk-…" />
              <div class="language-hint">{{ t('admin.llmKeyHint') }}</div>
            </div>
            <div v-if="llmFormError" class="admin-error">{{ llmFormError }}</div>
            <div class="form-actions">
              <button class="btn btn-ghost" :disabled="llmSaving" @click="llmFormOpen = false">
                {{ t('common.cancel') }}
              </button>
              <button
                class="btn btn-primary"
                :disabled="llmSaving || !llmForm.name.trim() || llmForm.key.trim().length < 8"
                @click="saveLlmKey"
              >
                {{ llmSaving ? t('settings.validating') : t('common.save') }}
              </button>
            </div>
          </div>
        </div>
      </template>

      <!-- ── Documents ────────────────────────────────────────────── -->
      <template v-if="activeTab === 'documents'">
        <div class="card">
          <div class="card-header">
            <div class="card-title">{{ t('admin.documentsTitle') }}</div>
            <span v-if="docs" class="badge badge-muted">{{ docs.total }}</span>
          </div>
          <div class="prompt-filters">
            <input
              v-model="docFilters.q"
              class="form-input filter-input"
              :placeholder="t('admin.fileName')"
              @keyup.enter="docsOffset = 0; loadDocuments()"
            />
            <select v-model="docFilters.status" class="form-input filter-select" @change="docsOffset = 0; loadDocuments()">
              <option value="">{{ t('admin.allStatuses') }}</option>
              <option v-for="status in ['pending', 'processing', 'done', 'failed']" :key="status" :value="status">
                {{ status }}
              </option>
            </select>
            <button class="btn btn-primary btn-sm" @click="docsOffset = 0; loadDocuments()">
              {{ t('common.refresh') }}
            </button>
          </div>
          <div v-if="docs && !docs.items.length" class="empty compact-empty">
            <div class="empty-title">{{ t('admin.noDocuments') }}</div>
          </div>
          <table v-if="docs && docs.items.length">
            <thead>
              <tr>
                <th>{{ t('admin.fileName') }}</th>
                <th>{{ t('admin.tenant') }}</th>
                <th>{{ t('admin.status') }}</th>
                <th>{{ t('admin.progress') }}</th>
                <th>{{ t('admin.size') }}</th>
                <th>{{ t('admin.created') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="doc in docs.items" :key="doc.id">
                <td class="file-name" :title="doc.error || doc.filename">{{ doc.filename }}</td>
                <td class="td-mono">{{ doc.tenant_id }}</td>
                <td>
                  <span :class="['badge', docBadge(doc.status)]">{{ doc.status }}</span>
                  <div v-if="doc.error" class="doc-error" :title="doc.error">{{ doc.error }}</div>
                </td>
                <td class="td-mono">
                  {{ doc.total_pages ? `${doc.processed_pages}/${doc.total_pages}` : '—' }}
                </td>
                <td class="td-mono">{{ fmtBytes(doc.size_bytes) }}</td>
                <td class="td-mono">{{ fmtDateTime(doc.created_at) }}</td>
              </tr>
            </tbody>
          </table>
          <div v-if="docs && docs.total > docs.limit" class="pager">
            <button class="btn btn-ghost btn-sm" :disabled="docsOffset === 0" @click="docsOffset -= docs.limit; loadDocuments()">
              ←
            </button>
            <span class="pager-label">{{ docsOffset + 1 }}–{{ Math.min(docsOffset + docs.limit, docs.total) }} / {{ docs.total }}</span>
            <button
              class="btn btn-ghost btn-sm"
              :disabled="docsOffset + docs.limit >= docs.total"
              @click="docsOffset += docs.limit; loadDocuments()"
            >
              →
            </button>
          </div>
        </div>
      </template>

      <!-- ── Usage ────────────────────────────────────────────────── -->
      <template v-if="activeTab === 'usage'">
        <div class="admin-toolbar sub">
          <span class="toolbar-label">{{ t('analytics.period') }}</span>
          <button
            v-for="d in [7, 14, 30]"
            :key="d"
            :class="['btn btn-ghost btn-sm', { 'btn-primary': usageDays === d }]"
            @click="usageDays = d"
          >
            {{ t('analytics.daysShort', { days: d }) }}
          </button>
        </div>

        <div v-if="usage" class="stats-grid">
          <div class="stat-card">
            <div class="stat-label">{{ t('admin.spend') }}</div>
            <div class="stat-value">{{ fmtCost(usage.totals.cost_usd) }}</div>
            <div class="stat-sub">{{ t('analytics.lastDays', { days: usage.days }) }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">{{ t('analytics.tokens') }}</div>
            <div class="stat-value">{{ fmtTokens(usage.totals.total_tokens) }}</div>
            <div class="stat-sub">prompt + completion</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">{{ t('analytics.requests') }}</div>
            <div class="stat-value">{{ usage.totals.calls }}</div>
            <div class="stat-sub">{{ t('analytics.metricLatency') }} {{ fmtMs(usage.totals.avg_latency_ms) }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">{{ t('admin.topTenant') }}</div>
            <div class="stat-value stat-value-sm">{{ usage.by_tenant[0]?.tenant_id || '—' }}</div>
            <div class="stat-sub">{{ usage.by_tenant[0] ? fmtCost(usage.by_tenant[0].cost_usd) : '' }}</div>
          </div>
        </div>

        <div v-if="usageTrend.length" class="card">
          <div class="card-header">
            <div>
              <div class="card-title">{{ t('analytics.trend') }}</div>
              <div class="card-sub">{{ t('admin.usageTrendSub') }}</div>
            </div>
          </div>
          <div class="trend-card-wrap"><TrendChart :days="usageTrend" /></div>
        </div>

        <div v-if="usage" class="usage-grid">
          <div class="card">
            <div class="card-header"><div class="card-title">{{ t('admin.byTenant') }}</div></div>
            <table>
              <thead>
                <tr>
                  <th>{{ t('admin.tenant') }}</th>
                  <th>{{ t('analytics.callCount') }}</th>
                  <th>{{ t('analytics.tokens') }}</th>
                  <th>{{ t('admin.cost') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in usage.by_tenant" :key="row.tenant_id">
                  <td class="td-mono">{{ row.tenant_id }}</td>
                  <td class="td-mono">{{ row.calls }}</td>
                  <td class="td-mono">{{ fmtTokens(row.total_tokens) }}</td>
                  <td class="td-mono">{{ fmtCost(row.cost_usd) }}</td>
                </tr>
                <tr v-if="!usage.by_tenant.length"><td colspan="4" class="td-mono">—</td></tr>
              </tbody>
            </table>
          </div>
          <div class="card">
            <div class="card-header"><div class="card-title">{{ t('admin.byModel') }}</div></div>
            <table>
              <thead>
                <tr>
                  <th>{{ t('analytics.model') }}</th>
                  <th>{{ t('analytics.callCount') }}</th>
                  <th>{{ t('analytics.tokens') }}</th>
                  <th>{{ t('admin.cost') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in usage.by_model" :key="`${row.provider}/${row.model}`">
                  <td><span class="tag">{{ row.model }}</span></td>
                  <td class="td-mono">{{ row.calls }}</td>
                  <td class="td-mono">{{ fmtTokens(row.total_tokens) }}</td>
                  <td class="td-mono">{{ fmtCost(row.cost_usd) }}</td>
                </tr>
                <tr v-if="!usage.by_model.length"><td colspan="4" class="td-mono">—</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>

      <!-- ── Health ───────────────────────────────────────────────── -->
      <template v-if="activeTab === 'health'">
        <div class="card">
          <div class="card-header">
            <div>
              <div class="card-title">{{ t('admin.healthTitle') }}</div>
              <div class="card-sub">{{ t('admin.healthSub') }}</div>
            </div>
            <span v-if="health" :class="['badge', health.status === 'ok' ? 'badge-green' : 'badge-red']">
              {{ health.status }}
            </span>
          </div>
          <div v-if="health" class="health-grid">
            <div v-for="(state, name) in health.checks" :key="name" class="health-check" :class="healthTone(state)">
              <div class="health-dot"></div>
              <div>
                <div class="health-name">{{ name }}</div>
                <div class="health-state">{{ state }}</div>
              </div>
            </div>
          </div>
        </div>
      </template>
    </template>

    <!-- Prompt detail modal -->
    <div v-if="detail" class="modal-overlay" @click.self="detail = null">
      <div class="modal prompt-modal">
        <div class="modal-title">{{ t('admin.promptDetail') }}</div>
        <div class="detail-grid">
          <div><span class="detail-label">{{ t('admin.tenant') }}</span><span class="td-mono">{{ detail.tenant_id }}</span></div>
          <div><span class="detail-label">{{ t('admin.user') }}</span>{{ promptActor(detail, settings.locale) }}</div>
          <div><span class="detail-label">{{ t('admin.key') }}</span>{{ detail.api_key_name || (detail.api_key_id ? String(detail.api_key_id).slice(0, 8) : '—') }}</div>
          <div><span class="detail-label">{{ t('admin.mode') }}</span><span class="tag">{{ detail.mode }}</span></div>
          <div><span class="detail-label">{{ t('admin.status') }}</span>{{ detail.status }}</div>
          <div><span class="detail-label">{{ t('admin.model') }}</span><span class="tag">{{ detail.model }}</span></div>
          <div><span class="detail-label">{{ t('admin.time') }}</span><span class="td-mono">{{ fmtDateTime(detail.created_at) }}</span></div>
          <div><span class="detail-label">{{ t('admin.latency') }}</span><span class="td-mono">{{ fmtMs(detail.latency_ms) }}</span></div>
          <div><span class="detail-label">{{ t('admin.cost') }}</span><span class="td-mono">{{ detail.cost_usd == null ? '—' : fmtCost(detail.cost_usd) }}</span></div>
          <div><span class="detail-label">{{ t('admin.tokens') }}</span><span class="td-mono">{{ detail.prompt_tokens }} / {{ detail.completion_tokens }}</span></div>
          <div><span class="detail-label">{{ t('admin.sources') }}</span><span class="td-mono">{{ detail.sources_count }}</span></div>
        </div>

        <div class="detail-block">
          <div class="detail-label">{{ t('admin.prompt') }}</div>
          <div class="detail-text">{{ detail.query }}</div>
        </div>
        <div v-if="detail.retrieval_query && detail.retrieval_query !== detail.query" class="detail-block">
          <div class="detail-label">{{ t('admin.retrievalQuery') }}</div>
          <div class="detail-text muted-text">{{ detail.retrieval_query }}</div>
        </div>
        <div class="detail-block">
          <div class="detail-label">{{ t('admin.answer') }}</div>
          <div class="detail-text">{{ detail.answer }}</div>
        </div>
        <div v-if="detail.error" class="detail-block error-block">
          <div class="detail-label">{{ t('admin.errorColumn') }}</div>
          <div class="detail-text">{{ detail.error }}</div>
        </div>

        <div class="form-actions">
          <button class="btn btn-ghost" @click="detail = null">{{ t('common.close') }}</button>
        </div>
      </div>
    </div>

    <!-- Create key modal -->
    <div v-if="createKeyOpen" class="modal-overlay" @click.self="createKeyOpen = false">
      <div class="modal key-modal">
        <div class="modal-title">{{ t('admin.createKey') }}</div>
        <div class="modal-sub">{{ t('admin.createKeySub') }}</div>

        <div class="form-group">
          <label class="form-label">{{ t('admin.tenant') }}</label>
          <input
            v-model="keyForm.tenantId"
            class="form-input"
            :placeholder="t('admin.tenantPlaceholder')"
            @input="onKeyFormTenantInput"
          />
        </div>
        <div class="form-group">
          <label class="form-label">{{ t('admin.keyName') }}</label>
          <input
            v-model="keyForm.name"
            class="form-input"
            :placeholder="t('admin.keyNamePlaceholder')"
          />
        </div>
        <div class="form-group">
          <label class="form-label">{{ t('admin.keyUser') }}</label>
          <select v-model="keyForm.userId" class="form-input">
            <option value="">{{ t('admin.noUser') }}</option>
            <option v-for="user in keyFormUsers" :key="user.id" :value="user.id">
              {{ user.name }} ({{ user.role }})
            </option>
          </select>
          <div class="language-hint">{{ t('admin.keyUserHint') }}</div>
        </div>

        <div v-if="createKeyError" class="admin-error">{{ createKeyError }}</div>

        <div class="form-actions">
          <button class="btn btn-ghost" :disabled="creatingKey" @click="createKeyOpen = false">
            {{ t('common.cancel') }}
          </button>
          <button
            class="btn btn-primary"
            :disabled="creatingKey || !keyForm.tenantId.trim() || !keyForm.name.trim()"
            @click="createKey"
          >
            {{ creatingKey ? t('settings.validating') : t('admin.createKey') }}
          </button>
        </div>
      </div>
    </div>

    <!-- Created key: raw_key shown once -->
    <div v-if="createdKey" class="modal-overlay" @click.self="createdKey = null">
      <div class="modal key-modal">
        <div class="modal-title">{{ t('admin.keyCreated') }}</div>
        <div class="modal-sub">{{ t('admin.keyCreatedHint') }}</div>
        <div class="raw-key-row">
          <code class="raw-key">{{ createdKey.raw_key }}</code>
          <button class="btn btn-ghost btn-sm" @click="copyRawKey">
            {{ rawKeyCopied ? t('chat.copied') : t('chat.copy') }}
          </button>
        </div>
        <div class="language-hint">{{ t('admin.keyCreatedWarning') }}</div>
        <div class="form-actions">
          <button class="btn btn-primary" @click="createdKey = null">{{ t('common.close') }}</button>
        </div>
      </div>
    </div>

    <!-- Revoke confirmation -->
    <ConfirmModal
      v-if="revokeTarget"
      :title="`${revokeTarget.name || revokeTarget.id}`"
      :heading="t('admin.revokeKeyTitle')"
      :warning="t('admin.revokeKeyWarning')"
      :confirm-label="t('admin.revoke')"
      @confirm="revokeKey"
      @cancel="revokeTarget = null"
    />
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useApi } from '@/composables/useApi'
import { useSessionStore } from '@/stores/session'
import { useSettingsStore } from '@/stores/settings'
import { useI18n } from '@/composables/useI18n'
import AppIcon from '@/components/AppIcon.vue'
import TrendChart from '@/components/TrendChart.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import { formatTokens, formatMs } from '@/utils/analytics'
import {
  PROMPT_MODES,
  PROMPT_STATUSES,
  buildCreateKeyPayload,
  buildPromptQueryParams,
  buildQueryTrend,
  buildUsageTrend,
  documentTone,
  formatBytes,
  formatCost,
  formatDateTime,
  healthTone,
  keyDisplayName,
  keyUserLabel,
  promptActor,
  promptStatusTone,
} from '@/utils/admin'

const { apiAdminFetch } = useApi()
const settings = useSettingsStore()
const session = useSessionStore()
const { t } = useI18n()

const tabs = [
  { id: 'overview', labelKey: 'admin.tabOverview' },
  { id: 'prompts', labelKey: 'admin.tabPrompts' },
  { id: 'users', labelKey: 'admin.tabUsers' },
  { id: 'keys', labelKey: 'admin.tabKeys' },
  { id: 'llm', labelKey: 'admin.tabLlm' },
  { id: 'documents', labelKey: 'admin.tabDocuments' },
  { id: 'usage', labelKey: 'admin.tabUsage' },
  { id: 'health', labelKey: 'admin.tabHealth' },
]

const activeTab = ref('overview')
const secretInput = ref('')
const error = ref(null)

const overview = ref(null)
const tenants = ref([])
const users = ref(null)
const keys = ref(null)
const showRevokedKeys = ref(false)
const docs = ref(null)
const usage = ref(null)
const health = ref(null)
const detail = ref(null)

const createKeyOpen = ref(false)
const creatingKey = ref(false)
const createKeyError = ref('')
const keyForm = ref({ tenantId: '', name: '', userId: '' })
const keyFormUsers = ref([])
const createdKey = ref(null)
const rawKeyCopied = ref(false)
const revokeTarget = ref(null)

const llmKeys = ref(null)
const llmFormOpen = ref(false)
const llmSaving = ref(false)
const llmFormError = ref('')
const llmForm = ref({ provider: 'moonshot', name: '', key: '' })
const llmDeleteTarget = ref(null)

const userFormOpen = ref(false)
const userSaving = ref(false)
const userFormError = ref('')
const userForm = ref({ email: '', name: '', password: '', role: 'member' })

const filters = ref({ q: '', tenantId: '', mode: '', status: '', days: 30 })
const prompts = ref(null)
const promptsOffset = ref(0)
const docFilters = ref({ q: '', status: '' })
const docsOffset = ref(0)
const usageDays = ref(7)

const loading = ref(false)
let pending = 0

function applySecret() {
  settings.setAdminSecret(secretInput.value)
  secretInput.value = ''
  load()
}

async function _call(path, assign) {
  pending += 1
  loading.value = true
  try {
    error.value = null
    assign(await apiAdminFetch(path))
  } catch (e) {
    error.value = e.message
  } finally {
    pending -= 1
    if (pending <= 0) { pending = 0; loading.value = false }
  }
}

function loadOverview() {
  return _call('/admin/overview', (data) => { overview.value = data })
}
function loadTenants() {
  return _call('/admin/tenants', (data) => { tenants.value = data })
}
function loadUsers() {
  return _call('/admin/users', (data) => { users.value = data })
}
function loadKeys() {
  return _call('/admin/keys', (data) => { keys.value = data })
}
function loadLlmKeys() {
  return _call('/admin/llm-keys', (data) => { llmKeys.value = data })
}

async function saveUser() {
  userSaving.value = true
  userFormError.value = ''
  try {
    await apiAdminFetch('/admin/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: userForm.value.email.trim(),
        name: userForm.value.name.trim(),
        password: userForm.value.password,
        role: userForm.value.role,
      }),
    })
    userFormOpen.value = false
    userForm.value = { email: '', name: '', password: '', role: 'member' }
    loadUsers()
  } catch (e) {
    userFormError.value = e.message
  } finally {
    userSaving.value = false
  }
}

async function saveLlmKey() {
  llmSaving.value = true
  llmFormError.value = ''
  try {
    await apiAdminFetch('/admin/llm-keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: llmForm.value.provider,
        name: llmForm.value.name.trim(),
        key: llmForm.value.key.trim(),
      }),
    })
    llmFormOpen.value = false
    llmForm.value = { provider: llmForm.value.provider, name: '', key: '' }
    loadLlmKeys()
  } catch (e) {
    llmFormError.value = e.message
  } finally {
    llmSaving.value = false
  }
}

async function deleteLlmKey(key) {
  if (llmDeleteTarget.value?.id === key.id) {
    llmDeleteTarget.value = null
    try {
      await apiAdminFetch(`/admin/llm-keys/${key.id}`, { method: 'DELETE' })
    } catch (e) {
      error.value = e.message
    }
    loadLlmKeys()
    return
  }
  llmDeleteTarget.value = key
  setTimeout(() => { if (llmDeleteTarget.value?.id === key.id) llmDeleteTarget.value = null }, 3000)
}
function loadPrompts() {
  const params = buildPromptQueryParams(filters.value, { limit: 50, offset: promptsOffset.value })
  return _call(`/admin/prompts?${params}`, (data) => { prompts.value = data })
}
function loadDocuments() {
  const params = new URLSearchParams()
  if (docFilters.value.q) params.set('q', docFilters.value.q)
  if (docFilters.value.status) params.set('status', docFilters.value.status)
  params.set('limit', '50')
  params.set('offset', String(docsOffset.value))
  return _call(`/admin/documents?${params}`, (data) => { docs.value = data })
}
function loadUsage() {
  return _call(`/admin/usage?days=${usageDays.value}`, (data) => { usage.value = data })
}
function loadHealth() {
  return _call('/admin/health', (data) => { health.value = data })
}

function load() {
  if (!settings.hasAdminSecret && !session.isAdmin) return
  if (activeTab.value === 'overview') { loadOverview(); loadTenants() }
  else if (activeTab.value === 'prompts') loadPrompts()
  else if (activeTab.value === 'users') loadUsers()
  else if (activeTab.value === 'keys') loadKeys()
  else if (activeTab.value === 'llm') loadLlmKeys()
  else if (activeTab.value === 'documents') loadDocuments()
  else if (activeTab.value === 'usage') loadUsage()
  else if (activeTab.value === 'health') loadHealth()
}

function refresh() {
  if (activeTab.value === 'overview') {
    overview.value = null; tenants.value = []
  } else if (activeTab.value === 'prompts') prompts.value = null
  else if (activeTab.value === 'users') users.value = null
  else if (activeTab.value === 'keys') keys.value = null
  else if (activeTab.value === 'llm') llmKeys.value = null
  else if (activeTab.value === 'documents') docs.value = null
  else if (activeTab.value === 'usage') usage.value = null
  else if (activeTab.value === 'health') health.value = null
  load()
}

function openPrompt(id) {
  _call(`/admin/prompts/${id}`, (data) => { detail.value = data })
}

const visibleKeys = computed(() => {
  if (!keys.value) return []
  return showRevokedKeys.value ? keys.value : keys.value.filter((k) => k.is_active)
})

async function openCreateKey(user = null) {
  createKeyError.value = ''
  rawKeyCopied.value = false
  keyForm.value = {
    tenantId: user?.tenant_id || '',
    name: user ? `${user.name}-key` : '',
    userId: user?.id || '',
  }
  keyFormUsers.value = []
  createKeyOpen.value = true
  if (keyForm.value.tenantId) await refreshKeyFormUsers()
}

async function refreshKeyFormUsers() {
  const tenant = keyForm.value.tenantId.trim()
  if (!tenant) { keyFormUsers.value = []; return }
  try {
    keyFormUsers.value = await apiAdminFetch(`/admin/users?tenant_id=${encodeURIComponent(tenant)}`)
  } catch {
    keyFormUsers.value = []
  }
}

let tenantInputTimer = null
function onKeyFormTenantInput() {
  keyForm.value.userId = ''
  clearTimeout(tenantInputTimer)
  tenantInputTimer = setTimeout(refreshKeyFormUsers, 400)
}

async function createKey() {
  creatingKey.value = true
  createKeyError.value = ''
  try {
    createdKey.value = await apiAdminFetch('/auth/keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildCreateKeyPayload(keyForm.value)),
    })
    createKeyOpen.value = false
    loadKeys()
    if (activeTab.value === 'users') loadUsers()
  } catch (e) {
    createKeyError.value = e.message
  } finally {
    creatingKey.value = false
  }
}

async function revokeKey() {
  const target = revokeTarget.value
  revokeTarget.value = null
  if (!target) return
  try {
    await apiAdminFetch(`/auth/keys/${target.id}`, { method: 'DELETE' })
  } catch (e) {
    error.value = e.message
  }
  loadKeys()
  if (activeTab.value === 'users') loadUsers()
}

async function copyRawKey() {
  if (!createdKey.value?.raw_key) return
  try {
    await navigator.clipboard.writeText(createdKey.value.raw_key)
    rawKeyCopied.value = true
  } catch {
    rawKeyCopied.value = false
  }
}

watch(activeTab, load, { immediate: true })
watch(usageDays, loadUsage)
watch(() => settings.adminSecret, () => {
  overview.value = null; tenants.value = []; users.value = null; keys.value = null; llmKeys.value = null
  prompts.value = null; docs.value = null; usage.value = null; health.value = null
  load()
})

const queryTrend = computed(() => (
  overview.value ? buildQueryTrend(overview.value.daily_queries, settings.locale) : []
))
const usageTrend = computed(() => (
  usage.value ? buildUsageTrend(usage.value.daily, settings.locale) : []
))

const overviewCards = computed(() => {
  if (!overview.value) return []
  const data = overview.value
  return [
    { label: t('admin.tenants'), value: String(data.tenants) },
    { label: t('admin.users'), value: String(data.users), sub: `${data.active_api_keys} ${t('admin.activeKeys')}` },
    {
      label: t('admin.documents'),
      value: String(data.documents.total),
      sub: `${data.documents.done} done · ${data.documents.processing} → · ${data.documents.failed} ✕`,
    },
    { label: t('admin.chunks'), value: String(data.chunks) },
    { label: t('admin.sessions'), value: String(data.chat_sessions), sub: `${data.chat_messages} ${t('admin.messages')}` },
    {
      label: t('admin.queries'),
      value: String(data.queries.total),
      sub: `${t('admin.today')}: ${data.queries.today} · ${t('admin.errors')}: ${data.queries.errors}`,
    },
  ]
})

const fmtTokens = formatTokens
const fmtMs = formatMs
const fmtCost = formatCost
const fmtBytes = formatBytes
const fmtDateTime = (value) => formatDateTime(value, settings.locale)

function statusBadge(status) {
  return { good: 'badge-green', warn: 'badge-yellow', bad: 'badge-red' }[promptStatusTone(status)]
}
function docBadge(status) {
  return { good: 'badge-green', warn: 'badge-yellow', bad: 'badge-red' }[documentTone(status)]
}
</script>

<style scoped>
.admin-screen { gap: 18px; }
.admin-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
}
.admin-toolbar.sub { margin-bottom: -4px; }
.admin-tabs {
  display: flex;
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--s1);
  overflow-x: auto;
}
.admin-tab {
  border: 0;
  border-radius: 7px;
  padding: 7px 14px;
  background: transparent;
  color: var(--muted2);
  cursor: pointer;
  font-family: var(--font);
  font-size: 12.5px;
  font-weight: 600;
  white-space: nowrap;
}
.admin-tab.active {
  background: var(--s3);
  color: var(--text);
  box-shadow: inset 0 0 0 1px var(--border2);
}
.secret-pill {
  margin-left: auto;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 12px;
}
.secret-pill.invalid { color: var(--red); }
.admin-error {
  padding: 12px 16px;
  border: 1px solid color-mix(in oklch, var(--red) 30%, transparent);
  border-radius: 10px;
  background: color-mix(in oklch, var(--red) 10%, transparent);
  color: var(--red);
  font-size: 12px;
  overflow-wrap: anywhere;
}
.stat-sub {
  margin-top: 6px;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10.5px;
}
.stat-value-sm { font-size: 18px; overflow: hidden; text-overflow: ellipsis; }

/* secret gate */
.secret-gate { max-width: 520px; }
.secret-form {
  display: flex;
  gap: 10px;
  padding: 16px 18px 4px;
}
.secret-hint {
  padding: 8px 18px 16px;
  color: var(--muted);
  font-size: 11.5px;
}

/* query trend bars */
.query-bars {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  height: 160px;
  padding: 18px;
}
.query-bar-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  gap: 3px;
  height: 100%;
}
.query-bar {
  width: 100%;
  max-width: 34px;
  border-radius: 4px 4px 0 0;
}
.query-bar.queries { background: linear-gradient(180deg, var(--accent), color-mix(in oklch, var(--accent) 55%, transparent)); }
.query-bar.errors { background: var(--red); opacity: 0.85; }
.query-bar-label {
  color: var(--muted);
  font-family: var(--mono);
  font-size: 9.5px;
  white-space: nowrap;
}
.trend-legend {
  display: flex;
  gap: 12px;
  color: var(--muted);
  font-size: 11px;
}
.legend-swatch {
  display: inline-block;
  width: 8px;
  height: 8px;
  margin-right: 5px;
  border-radius: 2px;
  background: var(--accent);
}
.legend-swatch.errors { background: var(--red); }

/* prompts */
.prompt-filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
}
.filter-input { flex: 1; min-width: 180px; }
.filter-narrow { flex: 0 0 140px; min-width: 120px; }
.filter-select { flex: 0 0 auto; min-width: 110px; width: auto; }
.prompt-row { cursor: pointer; }
.prompt-cell {
  max-width: 420px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.col-query { min-width: 260px; }
.pager {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 18px;
}
.pager-label { color: var(--muted); font-family: var(--mono); font-size: 11.5px; }
.doc-error {
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--red);
  font-size: 11px;
  margin-top: 3px;
}

/* usage */
.usage-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.trend-card-wrap { padding: 12px 16px 16px; }

/* health */
.health-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
  padding: 18px;
}
.health-check {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: color-mix(in oklch, var(--s2) 60%, transparent);
}
.health-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.health-check.good .health-dot { background: var(--green); }
.health-check.bad .health-dot { background: var(--red); }
.health-name { font-weight: 600; font-size: 13px; }
.health-state { color: var(--muted); font-family: var(--mono); font-size: 10.5px; margin-top: 2px; }

/* detail modal */
.prompt-modal {
  width: 720px;
  max-height: calc(100vh - 32px);
  overflow-y: auto;
}

/* keys tab */
.keys-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.revoked-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--muted);
  font-size: 12px;
  cursor: pointer;
  user-select: none;
}
.key-modal {
  width: 480px;
  max-height: calc(100vh - 32px);
  overflow-y: auto;
}
.raw-key-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 16px 0 8px;
}
.raw-key {
  flex: 1;
  overflow-x: auto;
  padding: 12px 14px;
  border: 1px solid var(--border2);
  border-radius: 10px;
  background: var(--s1);
  color: var(--text);
  font-family: var(--mono);
  font-size: 12px;
  white-space: nowrap;
}
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 18px;
  margin: 16px 0;
  font-size: 12.5px;
}
.detail-grid > div { display: flex; gap: 8px; align-items: baseline; }
.detail-label {
  color: var(--muted);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  min-width: 90px;
}
.detail-block { margin-bottom: 14px; }
.detail-text {
  margin-top: 6px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--s1);
  font-size: 13px;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 260px;
  overflow-y: auto;
}
.muted-text { color: var(--muted2); }
.error-block .detail-text {
  border-color: color-mix(in oklch, var(--red) 30%, transparent);
  background: color-mix(in oklch, var(--red) 8%, transparent);
  color: var(--red);
}

@media (max-width: 900px) {
  .usage-grid { grid-template-columns: 1fr; }
  .prompt-modal { width: calc(100vw - 24px); }
  .secret-pill { display: none; }
}
</style>
