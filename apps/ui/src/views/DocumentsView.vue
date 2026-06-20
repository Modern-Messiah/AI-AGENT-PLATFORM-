<template>
    <div class="screen-body">
        <div class="kb-hero">
            <div>
                <div class="kb-eyebrow">{{ t("documents.eyebrow") }}</div>
                <h1>{{ t("documents.title") }}</h1>
                <p>{{ t("documents.description") }}</p>
            </div>
            <div class="kb-stats">
                <div class="kb-stat">
                    <span>{{ stats.ready }}</span>
                    <label>{{ t("documents.ready") }}</label>
                </div>
                <div class="kb-stat">
                    <span>{{ stats.processing }}</span>
                    <label>{{ t("documents.processing") }}</label>
                </div>
                <div class="kb-stat" :class="{ warn: stats.failed }">
                    <span>{{ stats.failed }}</span>
                    <label>{{ t("documents.failed") }}</label>
                </div>
            </div>
        </div>

        <div
            :class="['drop-zone', { 'drag-over': dragging }]"
            @dragover.prevent="dragging = true"
            @dragleave="dragging = false"
            @drop="handleDrop"
            @click="fileInput.click()"
        >
            <div class="drop-icon">
                <AppIcon name="upload" :size="32" />
            </div>
            <div class="drop-title">{{ t("documents.uploadTitle") }}</div>
            <div class="drop-sub">{{ t("documents.uploadDescription") }}</div>
            <div class="drop-types">
                <span
                    v-for="type in [
                        'PDF',
                        'DOCX',
                        'TXT',
                        'MD',
                        'CSV',
                        'HTML',
                        'PNG',
                        'JPG',
                        'WEBP',
                    ]"
                    :key="type"
                    class="type-chip"
                    >.{{ type.toLowerCase() }}</span
                >
            </div>
            <input
                ref="fileInput"
                type="file"
                multiple
                accept="application/pdf,.docx,.txt,.md,.csv,.html,image/png,image/jpeg,image/webp"
                style="display: none"
                @change="handleFileInput"
            />
        </div>

        <form class="url-source-panel" @submit.prevent="checkUrlSource">
            <div>
                <div class="url-source-title">
                    {{ t("documents.urlTitle") }}
                </div>
                <div class="url-source-sub">
                    {{ t("documents.urlDescription") }}
                </div>
            </div>
            <div class="url-source-controls">
                <input
                    v-model.trim="urlInput"
                    class="url-source-input"
                    type="url"
                    :placeholder="t('documents.urlPlaceholder')"
                    autocomplete="off"
                />
                <button
                    class="btn btn-ghost"
                    type="submit"
                    :disabled="urlChecking || urlAdding"
                >
                    <span v-if="urlChecking">{{
                        t("documents.urlChecking")
                    }}</span>
                    <span v-else>{{ t("documents.urlCheck") }}</span>
                </button>
                <button
                    class="btn btn-ghost url-add-btn"
                    type="button"
                    :disabled="!canAddCheckedUrl || urlAdding"
                    @click="addUrlSource"
                >
                    <span v-if="urlAdding">{{ t("documents.urlAdding") }}</span>
                    <span v-else>{{ t("documents.urlAdd") }}</span>
                </button>
            </div>
            <div v-if="urlCheck?.ok" class="url-source-status ok">
                {{
                    urlCheck.source_type === "github"
                        ? t("documents.githubReady", {
                              count: urlCheck.file_count || 0,
                          })
                        : t("documents.urlReady", {
                              title:
                                  urlCheck.title ||
                                  urlCheck.final_url ||
                                  urlCheck.url,
                          })
                }}
                <div
                    v-if="
                        urlCheck.source_type === 'github' &&
                        urlCheck.preview_files?.length
                    "
                    class="url-source-preview-files"
                >
                    {{ urlCheck.preview_files.slice(0, 5).join(" · ") }}
                </div>
            </div>
            <div v-else-if="urlError" class="url-source-status error">
                {{ t("documents.urlRejected", { reason: urlError }) }}
            </div>
        </form>

        <div class="card documents-memory-card">
            <div class="card-header">
                <div>
                    <div class="card-title">
                        {{ t("documents.memoryFiles") }}
                    </div>
                    <div class="card-sub">
                        {{
                            t("documents.readyCount", {
                                ready: stats.ready,
                                total: stats.total,
                            })
                        }}
                    </div>
                </div>
                <div style="display: flex; gap: 8px; align-items: center">
                    <div
                        v-if="docs.length"
                        class="progress"
                        style="width: 100px"
                    >
                        <div
                            class="progress-fill"
                            :style="{ width: stats.progressPct + '%' }"
                        ></div>
                    </div>
                    <button
                        class="btn btn-ghost btn-sm"
                        :title="t('common.refresh')"
                        @click="loadDocs"
                    >
                        <AppIcon name="refresh" :size="11" />
                    </button>
                    <button
                        class="btn btn-ghost btn-sm"
                        :title="t('documents.clearList')"
                        @click="clearAll"
                    >
                        <AppIcon name="trash" :size="11" />
                    </button>
                </div>
            </div>

            <div v-if="docs.length === 0" class="empty" style="padding: 40px">
                <div class="empty-icon">📂</div>
                <div class="empty-title">{{ t("documents.emptyTitle") }}</div>
                <div class="empty-sub">
                    {{ t("documents.emptyDescription") }}
                </div>
            </div>
            <div v-else class="documents-table-scroll">
                <table class="documents-table">
                    <colgroup>
                        <col class="documents-col-file" />
                        <col class="documents-col-status" />
                        <col class="documents-col-size" />
                        <col class="documents-col-uploaded" />
                        <col class="documents-col-actions" />
                    </colgroup>
                    <thead>
                        <tr>
                            <th>{{ t("documents.file") }}</th>
                            <th>{{ t("documents.status") }}</th>
                            <th>{{ t("documents.size") }}</th>
                            <th>{{ t("documents.uploaded") }}</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="doc in docs" :key="doc.id">
                            <td>
                                <div class="file-name">
                                    <div class="file-icon">
                                        {{ sourceIcon(doc) }}
                                    </div>
                                    <div>
                                        <button
                                            class="file-title-button"
                                            type="button"
                                            :disabled="doc._pending"
                                            @click="openDocument(doc)"
                                        >
                                            {{ doc.name }}
                                        </button>
                                        <div
                                            v-if="isExternalSource(doc)"
                                            class="source-url"
                                        >
                                            <span class="source-pill">{{
                                                sourceBadge(doc)
                                            }}</span>
                                            <span class="source-url-text">{{
                                                doc.sourceUrl
                                            }}</span>
                                        </div>
                                        <div
                                            v-if="doc.error"
                                            style="
                                                font-size: 11px;
                                                color: var(--red);
                                                margin-top: 2px;
                                            "
                                        >
                                            {{ doc.error }}
                                        </div>
                                        <div
                                            style="
                                                font-size: 10px;
                                                color: var(--muted);
                                                font-family: var(--mono);
                                                margin-top: 1px;
                                            "
                                        >
                                            {{ doc.id }}
                                        </div>
                                    </div>
                                </div>
                            </td>
                            <td>
                                <div class="document-status">
                                    <div class="document-status-line">
                                        <StatusBadge :status="doc.status" />
                                        <div
                                            v-if="
                                                doc.status === 'processing' ||
                                                doc.status === 'pending'
                                            "
                                            class="spinner"
                                        ></div>
                                    </div>
                                    <div
                                        v-if="
                                            doc.totalPages > 0 &&
                                            doc.status !== 'done'
                                        "
                                        class="page-progress"
                                    >
                                        <div class="page-progress-label">
                                            {{
                                                t("documents.pageProgress", {
                                                    processed:
                                                        doc.processedPages,
                                                    total: doc.totalPages,
                                                })
                                            }}
                                        </div>
                                        <div class="progress">
                                            <div
                                                class="progress-fill"
                                                :style="{
                                                    width:
                                                        doc.progressPct + '%',
                                                }"
                                            ></div>
                                        </div>
                                    </div>
                                </div>
                            </td>
                            <td class="td-mono">{{ doc.size }}</td>
                            <td class="td-mono">{{ doc.time }}</td>
                            <td class="documents-actions-cell">
                                <div class="document-row-actions">
                                    <button
                                        class="btn btn-ghost btn-sm"
                                        :title="t('documents.openDocument')"
                                        :disabled="doc._pending"
                                        @click="openDocument(doc)"
                                    >
                                        <AppIcon name="docs" />
                                    </button>
                                    <button
                                        class="btn btn-ghost btn-sm"
                                        :title="t('documents.reindex')"
                                        :disabled="!canReindexDocument(doc)"
                                        @click="reindexDoc(doc)"
                                    >
                                        <AppIcon name="refresh" />
                                    </button>
                                    <button
                                        class="btn btn-ghost btn-sm"
                                        :title="t('common.delete')"
                                        @click="removeDoc(doc.id)"
                                    >
                                        <AppIcon name="trash" />
                                    </button>
                                </div>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>

        <AppToast v-if="toast" v-bind="toast" @done="toast = null" />
    </div>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { useApi } from "@/composables/useApi";
import { useSettingsStore } from "@/stores/settings";
import { useI18n } from "@/composables/useI18n";
import AppIcon from "@/components/AppIcon.vue";
import AppToast from "@/components/AppToast.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import {
    buildDocumentRoute,
    canReindexDocument,
    formatFileSize,
    knowledgeBaseStats,
    normalizeDocument,
} from "@/utils/documents";

const { apiFetch } = useApi();
const settings = useSettingsStore();
const { t } = useI18n();
const router = useRouter();

const docs = ref([]);
const dragging = ref(false);
const toast = ref(null);
const fileInput = ref(null);
const urlInput = ref("");
const urlCheck = ref(null);
const urlError = ref("");
const checkedUrl = ref("");
const urlChecking = ref(false);
const urlAdding = ref(false);

async function loadDocs() {
    if (!settings.isConnected) {
        docs.value = [];
        return;
    }
    try {
        const data = await apiFetch("/documents");
        // merge: keep in-progress uploads that aren't in the API list yet
        const apiIds = new Set(data.map((d) => d.id));
        const pending = docs.value.filter(
            (d) => d._pending && !apiIds.has(d.id),
        );
        docs.value = [
            ...pending,
            ...data.map((doc) => normalizeDocument(doc, settings.locale)),
        ];
    } catch {
        docs.value = [];
    }
}

watch([() => settings.apiKey, () => settings.locale], loadDocs, {
    immediate: true,
});

const stats = computed(() => knowledgeBaseStats(docs.value));
const canAddCheckedUrl = computed(() =>
    Boolean(
        urlCheck.value?.ok &&
        checkedUrl.value &&
        checkedUrl.value === urlInput.value.trim() &&
        !urlChecking.value,
    ),
);

watch(urlInput, () => {
    urlCheck.value = null;
    urlError.value = "";
    checkedUrl.value = "";
});

function mimeIcon(name) {
    const ext = (name || "").split(".").pop().toLowerCase();
    return (
        {
            pdf: "📄",
            md: "📝",
            txt: "📃",
            csv: "📊",
            html: "🌐",
            docx: "📘",
            png: "🖼️",
            jpg: "🖼️",
            jpeg: "🖼️",
            webp: "🖼️",
        }[ext] || "📁"
    );
}

function sourceIcon(doc) {
    return isExternalSource(doc) ? "🌐" : mimeIcon(doc?.name);
}

function isExternalSource(doc) {
    return doc?.sourceType === "url" || doc?.sourceType === "github";
}

function sourceBadge(doc) {
    return doc?.sourceType === "github"
        ? t("documents.githubBadge")
        : t("documents.urlBadge");
}

function openDocument(doc) {
    if (doc?._pending) return;
    router.push(buildDocumentRoute(doc.id));
}

async function removeDoc(id) {
    const doc = docs.value.find((d) => d.id === id);
    if (doc?._pending) {
        docs.value = docs.value.filter((d) => d.id !== id);
        return;
    }
    try {
        await apiFetch(`/documents/${id}`, { method: "DELETE" });
        docs.value = docs.value.filter((d) => d.id !== id);
    } catch (e) {
        toast.value = {
            msg: t("documents.deleteError", { message: e.message }),
            type: "error",
        };
    }
}

async function reindexDoc(doc) {
    if (!canReindexDocument(doc)) return;
    updateDoc(doc.id, { status: "pending", error: null, _pending: true });
    toast.value = {
        msg: t("documents.reindexing", { name: doc.name }),
        type: "info",
    };
    try {
        await apiFetch(`/documents/${doc.id}/reindex`, { method: "POST" });
        pollStatus(doc.id);
    } catch (e) {
        updateDoc(doc.id, {
            status: "failed",
            error: e.message,
            _pending: false,
        });
        toast.value = {
            msg: t("documents.reindexError", { message: e.message }),
            type: "error",
        };
    }
}

async function clearAll() {
    const toDelete = docs.value.filter((d) => !d._pending);
    if (!toDelete.length) {
        docs.value = docs.value.filter((d) => d._pending);
        return;
    }
    const failed = [];
    await Promise.all(
        toDelete.map(async (doc) => {
            try {
                await apiFetch(`/documents/${doc.id}`, { method: "DELETE" });
            } catch {
                failed.push(doc.id);
            }
        }),
    );
    docs.value = docs.value.filter((d) => d._pending || failed.includes(d.id));
    if (failed.length)
        toast.value = {
            msg: t("documents.deleteManyError", { count: failed.length }),
            type: "error",
        };
}
function updateDoc(id, patch) {
    docs.value = docs.value.map((d) => (d.id === id ? { ...d, ...patch } : d));
}

async function pollStatus(docId) {
    // Poll for up to 10 minutes (120 × 5s). Check immediately, then wait between attempts.
    for (let i = 0; i < 120; i++) {
        if (i > 0) await new Promise((r) => setTimeout(r, 5000));
        try {
            const data = await apiFetch(`/documents/${docId}`);
            const normalized = normalizeDocument(data, settings.locale);
            if (data.status === "done") {
                updateDoc(docId, { ...normalized, _pending: false });
                return;
            }
            if (data.status === "failed") {
                updateDoc(docId, {
                    ...normalized,
                    error: data.error || "Failed",
                    _pending: false,
                });
                return;
            }
            updateDoc(docId, { ...normalized, _pending: true });
        } catch {}
    }
    // After 10 min show 'processing' (not 'failed') — Temporal may still be running
    updateDoc(docId, { status: "processing", error: null, _pending: false });
}

async function uploadFile(file) {
    if (!settings.isConnected) {
        toast.value = { msg: t("documents.apiKeyRequired"), type: "error" };
        return;
    }
    const tempId = "upload-" + Date.now();
    const size = formatFileSize(file.size);
    docs.value = [
        {
            id: tempId,
            name: file.name,
            status: "processing",
            time: t("documents.now"),
            error: null,
            size,
            processedPages: 0,
            totalPages: 0,
            progressPct: 0,
            _pending: true,
        },
        ...docs.value,
    ];
    toast.value = {
        msg: t("documents.uploading", { name: file.name }),
        type: "info",
    };
    try {
        const form = new FormData();
        form.append("file", file);
        const data = await apiFetch("/documents", {
            method: "POST",
            body: form,
        });
        docs.value = docs.value.map((d) =>
            d.id === tempId ? { ...d, id: data.id, _pending: true } : d,
        );
        pollStatus(data.id);
    } catch (e) {
        updateDoc(tempId, { status: "failed", error: e.message });
        toast.value = {
            msg: t("common.error", { message: e.message }),
            type: "error",
        };
    }
}

async function checkUrlSource() {
    if (!settings.isConnected) {
        toast.value = { msg: t("documents.apiKeyRequired"), type: "error" };
        return;
    }
    const url = urlInput.value.trim();
    if (!url) {
        urlError.value = t("documents.urlRequired");
        return;
    }
    urlChecking.value = true;
    urlCheck.value = null;
    urlError.value = "";
    checkedUrl.value = "";
    try {
        const data = await apiFetch("/documents/url/check", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url }),
        });
        if (data.ok) {
            urlCheck.value = data;
            checkedUrl.value = url;
        } else {
            urlError.value = data.reason || "URL rejected";
        }
    } catch (e) {
        urlError.value = e.message;
    } finally {
        urlChecking.value = false;
    }
}

async function addUrlSource() {
    if (!canAddCheckedUrl.value || urlAdding.value) return;
    const url = checkedUrl.value;
    urlAdding.value = true;
    try {
        const data = await apiFetch("/documents/url", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url }),
        });
        const normalized = normalizeDocument(data, settings.locale);
        docs.value = [
            { ...normalized, _pending: true },
            ...docs.value.filter((d) => d.id !== normalized.id),
        ];
        toast.value = {
            msg: t("documents.urlAdded", { name: normalized.name }),
            type: "info",
        };
        urlInput.value = "";
        urlCheck.value = null;
        urlError.value = "";
        checkedUrl.value = "";
        pollStatus(data.id);
    } catch (e) {
        urlError.value = e.message;
        toast.value = {
            msg: t("common.error", { message: e.message }),
            type: "error",
        };
    } finally {
        urlAdding.value = false;
    }
}

function handleDrop(e) {
    e.preventDefault();
    dragging.value = false;
    Array.from(e.dataTransfer.files).forEach(uploadFile);
}
function handleFileInput(e) {
    Array.from(e.target.files).forEach(uploadFile);
    e.target.value = "";
}
</script>

<style scoped>
.kb-hero {
    display: flex;
    justify-content: space-between;
    gap: 24px;
    padding: 18px;
    border: 1px solid var(--border);
    border-radius: 14px;
    background:
        radial-gradient(
            circle at 10% 0%,
            color-mix(in oklch, var(--purple) 18%, transparent),
            transparent 28%
        ),
        var(--s1);
}
.kb-eyebrow {
    margin-bottom: 6px;
    color: var(--accent);
    font-family: var(--mono);
    font-size: 10px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
.kb-hero h1 {
    margin: 0 0 8px;
    font-size: 24px;
    letter-spacing: -0.04em;
}
.kb-hero p {
    max-width: 620px;
    color: var(--muted2);
    font-size: 13px;
    line-height: 1.6;
}
.kb-stats {
    display: grid;
    grid-template-columns: repeat(3, minmax(84px, 1fr));
    gap: 8px;
    min-width: 280px;
}
.kb-stat {
    padding: 12px;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: color-mix(in oklch, var(--s2) 86%, transparent);
}
.kb-stat span {
    display: block;
    color: var(--text);
    font-family: var(--mono);
    font-size: 20px;
    font-weight: 700;
}
.kb-stat label {
    color: var(--muted);
    font-size: 11px;
}
.kb-stat.warn span {
    color: var(--red);
}
.url-source-panel {
    display: grid;
    grid-template-columns: minmax(220px, 0.8fr) minmax(320px, 1.2fr);
    gap: 14px;
    align-items: start;
    padding: 14px;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--s1);
}
.url-source-title {
    color: var(--text);
    font-size: 13px;
    font-weight: 700;
}
.url-source-sub,
.source-url {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    align-items: center;
    margin-top: 3px;
    color: var(--muted);
    font-size: 11px;
    line-height: 1.45;
}
.url-source-sub {
    display: block;
}
.source-pill {
    padding: 1px 6px;
    border: 1px solid color-mix(in oklch, var(--accent) 35%, transparent);
    border-radius: 999px;
    background: color-mix(in oklch, var(--accent) 10%, transparent);
    color: var(--accent);
    font-family: var(--mono);
    font-size: 9px;
    font-weight: 700;
    text-transform: uppercase;
}
.url-source-controls {
    display: grid;
    grid-template-columns: minmax(220px, 1fr) auto auto;
    gap: 8px;
}
.url-source-input {
    width: 100%;
    min-width: 0;
    height: 38px;
    padding: 0 12px;
    border: 1px solid var(--border);
    border-radius: 10px;
    outline: none;
    background: linear-gradient(
        180deg,
        color-mix(in oklch, var(--s2) 92%, var(--text) 3%),
        var(--s2)
    );
    box-shadow: inset 0 1px 0 color-mix(in oklch, var(--text) 4%, transparent);
    color: var(--text);
    font-family: var(--font);
    font-size: 13px;
    line-height: 38px;
    transition:
        border-color 0.16s ease,
        box-shadow 0.16s ease,
        background 0.16s ease;
}
.url-source-input::placeholder {
    color: var(--muted);
}
.url-source-input:hover {
    border-color: color-mix(in oklch, var(--accent) 38%, var(--border));
}
.url-source-input:focus {
    border-color: color-mix(in oklch, var(--accent) 72%, var(--border));
    background: color-mix(in oklch, var(--s2) 94%, var(--accent) 6%);
    box-shadow:
        0 0 0 3px color-mix(in oklch, var(--accent) 14%, transparent),
        inset 0 1px 0 color-mix(in oklch, var(--text) 5%, transparent);
}
.url-source-input:disabled {
    cursor: not-allowed;
    opacity: 0.55;
}
.url-add-btn:disabled {
    border-color: var(--border);
    background: transparent;
    color: var(--muted2);
    box-shadow: none;
    opacity: 0.72;
}
.url-add-btn:disabled:hover {
    border-color: var(--border);
    background: transparent;
    color: var(--muted2);
    box-shadow: none;
    opacity: 0.72;
}
.url-source-status {
    grid-column: 2;
    font-size: 11px;
    line-height: 1.45;
}
.url-source-status.ok {
    color: var(--green);
}
.url-source-status.error {
    color: var(--red);
}
.url-source-preview-files {
    max-width: 100%;
    margin-top: 3px;
    overflow: hidden;
    color: var(--muted);
    font-family: var(--mono);
    text-overflow: ellipsis;
    white-space: nowrap;
}
.documents-table-scroll {
    flex: 1 1 auto;
    min-height: 0;
    overflow-x: hidden;
    overflow-y: auto;
    scrollbar-color: color-mix(in oklch, var(--muted2) 42%, var(--border2))
        transparent;
    scrollbar-width: thin;
    scrollbar-gutter: stable;
}
.documents-table-scroll table {
    width: 100%;
    min-width: 0;
    table-layout: fixed;
}
.documents-table-scroll th,
.documents-table-scroll td {
    overflow: hidden;
    padding-inline: 12px;
}
.documents-table-scroll th:first-child,
.documents-table-scroll td:first-child {
    padding-left: 18px;
}
.documents-table-scroll th:last-child,
.documents-table-scroll td:last-child {
    padding-right: 18px;
}
.documents-col-status {
    width: 148px;
}
.documents-col-size {
    width: 82px;
}
.documents-col-uploaded {
    width: 126px;
}
.documents-col-actions {
    width: 154px;
}
.documents-actions-cell {
    padding-left: 6px;
    padding-right: 18px;
}
.documents-table-scroll thead {
    position: sticky;
    top: 0;
    z-index: 1;
    background: var(--s1);
    box-shadow: 0 1px 0 var(--border);
}
.documents-table-scroll::-webkit-scrollbar {
    width: 12px;
    height: 12px;
}
.documents-table-scroll::-webkit-scrollbar-track {
    background: transparent;
}
.documents-table-scroll::-webkit-scrollbar-thumb {
    border: 3px solid var(--s1);
    border-radius: 999px;
    background: color-mix(in oklch, var(--muted2) 42%, var(--border2));
}
.documents-table-scroll::-webkit-scrollbar-thumb:hover {
    background: color-mix(in oklch, var(--muted2) 58%, var(--border2));
}
.documents-memory-card {
    display: flex;
    flex-direction: column;
    flex: 0 0 clamp(460px, 48vh, 620px);
    min-height: 460px;
    max-height: 620px;
}
.file-title-button {
    display: block;
    max-width: 100%;
    overflow: hidden;
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--text);
    cursor: pointer;
    font-family: var(--font);
    font-size: 13px;
    text-overflow: ellipsis;
    text-align: left;
    white-space: nowrap;
}
.file-title-button:hover {
    color: var(--accent);
}
.file-title-button:disabled {
    color: var(--muted2);
    cursor: not-allowed;
}
.document-status {
    display: grid;
    gap: 7px;
    min-width: 0;
}
.document-status-line {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
}
.page-progress {
    display: grid;
    gap: 4px;
}
.page-progress-label {
    color: var(--muted);
    font-family: var(--mono);
    font-size: 9px;
    white-space: nowrap;
}
.page-progress .progress {
    width: 100%;
    min-width: 0;
}
.documents-table-scroll .file-name {
    min-width: 0;
}
.documents-table-scroll .file-name > div:last-child {
    min-width: 0;
    max-width: 100%;
}
.source-url-text {
    min-width: 0;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.document-row-actions {
    display: flex;
    gap: 6px;
    justify-content: flex-end;
}
.document-row-actions .btn-sm {
    width: 36px;
    height: 36px;
    flex: 0 0 36px;
    justify-content: center;
    padding: 0;
}

@media (max-width: 900px) {
    .kb-hero {
        flex-direction: column;
    }
    .kb-stats {
        min-width: 0;
    }
    .url-source-panel {
        grid-template-columns: 1fr;
    }
    .url-source-controls {
        grid-template-columns: 1fr;
    }
    .url-source-status {
        grid-column: 1;
    }
}
</style>
