import MarkdownIt from 'markdown-it'
import createDOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/common'

// Chat answers are LLM markdown: headings, lists, tables, fenced code.
// breaks:true keeps the chat feel of single newlines (previous pre-wrap UI).
const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  highlight(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre><code class="hljs language-${lang}">${hljs.highlight(code, { language: lang }).value}</code></pre>`
      } catch { /* fall through to escaped output */ }
    }
    return `<pre><code class="hljs">${md.utils.escapeHtml(code)}</code></pre>`
  },
})

// DOMPurify needs a window; in Node (unit tests) it is unavailable and we
// render without sanitizing — the browser build always sanitizes.
const purifier = typeof window !== 'undefined' ? createDOMPurify(window) : null

export function renderMarkdown(text) {
  const html = md.render(text ?? '')
  if (!purifier) return html
  return purifier.sanitize(html, {
    ADD_ATTR: ['target'],
    FORBID_TAGS: ['style', 'form', 'input', 'iframe', 'object', 'embed'],
    FORBID_ATTR: ['style'],
  })
}

export function stripMarkdown(text) {
  return md.render(text ?? '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}
