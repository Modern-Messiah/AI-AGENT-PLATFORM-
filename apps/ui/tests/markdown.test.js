import test from 'node:test'
import assert from 'node:assert/strict'

import { renderMarkdown, stripMarkdown } from '../src/utils/markdown.js'


test('renders core markdown constructs used by LLM answers', () => {
  const html = renderMarkdown(
    '## Заголовок\n\n- пункт один\n- пункт два\n\n`inline code` и **жирный** текст.'
  )
  assert.match(html, /<h2>Заголовок<\/h2>/)
  assert.match(html, /<ul>/)
  assert.match(html, /<li>пункт один<\/li>/)
  assert.match(html, /<code>inline code<\/code>/)
  assert.match(html, /<strong>жирный<\/strong>/)
})


test('highlights fenced code blocks and escapes raw html', () => {
  const html = renderMarkdown('```python\nprint("hi <script>")\n```')
  assert.match(html, /<pre><code class="hljs language-python">/)
  // the script tag inside code must be escaped, never live
  assert.ok(!html.includes('<script>'))
  assert.match(html, /&lt;script&gt;/)
})


test('single newlines behave like chat lines (breaks: true)', () => {
  const html = renderMarkdown('строка одна\nстрока две')
  assert.match(html, /<br\s*\/?>/)
})


test('raw html in message text is not rendered as markup', () => {
  const html = renderMarkdown('<img src=x onerror=alert(1)> текст')
  // markdown-it with html:false escapes it — the tag must not survive as markup
  assert.ok(!/<img\s/.test(html), `unexpected live tag: ${html}`)
})


test('tables render', () => {
  const html = renderMarkdown('| a | b |\n|---|---|\n| 1 | 2 |')
  assert.match(html, /<table>/)
  assert.match(html, /<th>a<\/th>/)
})


test('stripMarkdown flattens to plain text', () => {
  const plain = stripMarkdown('## Заголовок\n\n**жирный** и `код`')
  assert.equal(plain, 'Заголовок жирный и код')
})


test('empty input renders empty html', () => {
  assert.equal(renderMarkdown(''), '')
  assert.equal(renderMarkdown(null), '')
  assert.equal(renderMarkdown(undefined), '')
})
