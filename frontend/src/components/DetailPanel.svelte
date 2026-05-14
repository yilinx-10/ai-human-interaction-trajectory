<script>
  // @ts-nocheck  — data nodes come from dynamic JSON; type safety via logic, not annotations
  import { selectedItem } from '../stores.js'

  // Must stay in sync with NODE_COLOR in ForceGraph.svelte
  const TYPE_COLOR = {
    claim:      '#93c5fd',
    evidence:   '#fde68a',
    conclusion: '#6ee7b7',
    constraint: '#fdba74',
    other:      '#cbd5e1',
  }

  const ORIGIN_COLOR = { user: '#f0e9de', model: '#a9baab', 'co-constructed': '#705a89' }
  const ORIGIN_LABEL = { user: 'User-introduced', model: 'Model-introduced', 'co-constructed': 'Co-constructed' }

  const SCHEME_LABEL = {
    causal:      'causal',
    evidential:  'evidential',
    expert:      'expert',
    analogical:  'analogical',
    consequence: 'consequence',
    example:     'example',
    other:       null,
  }

  function typeShapeSvg(type, color) {
    const fill   = color ?? '#cbd5e1'
    const stroke = '#3a4060'
    switch (type) {
      case 'claim':
        return `<svg width="14" height="14"><rect x="1" y="2" width="12" height="9" rx="2" fill="${fill}" stroke="${stroke}" stroke-width="1"/></svg>`
      case 'evidence':
        return `<svg width="14" height="14"><polygon points="7,1 13,7 7,13 1,7" fill="${fill}" stroke="${stroke}" stroke-width="1"/></svg>`
      case 'conclusion':
        return `<svg width="14" height="14"><circle cx="7" cy="7" r="6" fill="${fill}" stroke="${stroke}" stroke-width="1"/></svg>`
      case 'constraint':
        return `<svg width="14" height="14"><polygon points="1,13 13,13 7,1" fill="${fill}" stroke="${stroke}" stroke-width="1"/></svg>`
      default:
        return `<svg width="14" height="14"><circle cx="7" cy="7" r="6" fill="${fill}" stroke="${stroke}" stroke-width="1" stroke-dasharray="2,1.5"/></svg>`
    }
  }

  function parseTurns(fullText) {
    if (!fullText) return []
    return fullText.split(/(?=\[HUMAN\]|\[ASSISTANT\])/).filter(Boolean).map(t => {
      const sender = t.startsWith('[HUMAN]') ? 'human' : 'assistant'
      const text = t.replace(/^\[(HUMAN|ASSISTANT)\]\s*/, '').trim()
      return { sender, text }
    })
  }

  function fmt(dateStr) {
    if (!dateStr) return ''
    return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  }

  // ── In-conversation occurrence matching ─────────────────────────────────────

  let _convCache = null
  async function fetchConversations() {
    if (!_convCache) {
      const r = await fetch('/data/conversations.json')
      _convCache = await r.json()
    }
    return _convCache
  }

  const OCC_STOP = new Set([
    'the','a','an','is','are','was','were','be','been','being','have','has','had',
    'do','does','did','will','would','could','should','may','might','shall','can',
    'to','of','in','on','at','by','for','with','about','from','into','and','but',
    'or','not','i','you','he','she','it','we','they','this','that','these','those',
    'what','which','who','my','your','his','its','our','their','me','him','her',
    'also','just','more','very','here','there','when','then','than','so','such',
    'any','all','each','both','been','use','used','using',
  ])

  // Extract unigrams (content words) and bigrams (adjacent content-word pairs,
  // with up to 2 function words between them) from a node's text_long.
  function extractTerms(text) {
    const words = (text ?? '').toLowerCase()
      .replace(/[^a-z0-9\s]/g, ' ')
      .split(/\s+/)
      .filter(w => w.length >= 3)

    const isContent = w => w.length >= 4 && !OCC_STOP.has(w)
    const unigrams = [...new Set(words.filter(isContent))]

    // Build bigrams: phrase from one content word to the next (≤2 words between)
    const bigrams = []
    for (let i = 0; i < words.length; i++) {
      if (!isContent(words[i])) continue
      for (let j = i + 1; j < words.length && j <= i + 3; j++) {
        if (isContent(words[j])) {
          bigrams.push(words.slice(i, j + 1).join(' '))
          break
        }
      }
    }

    return { unigrams, bigrams: [...new Set(bigrams)] }
  }

  function buildSegments(windowText, keywords) {
    if (!keywords.length) return [{ text: windowText, hl: false }]
    const escaped = keywords.map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    const re = new RegExp(`(${escaped.join('|')})`, 'gi')
    const segs = []
    let cursor = 0, m
    while ((m = re.exec(windowText)) !== null) {
      if (m.index > cursor) segs.push({ text: windowText.slice(cursor, m.index), hl: false })
      segs.push({ text: m[0], hl: true })
      cursor = m.index + m[0].length
    }
    if (cursor < windowText.length) segs.push({ text: windowText.slice(cursor), hl: false })
    return segs
  }

  function getExcerpt(turnText, keywords, windowSize = 300) {
    if (turnText.length <= windowSize) {
      return { segments: buildSegments(turnText, keywords), prefix: false, suffix: false }
    }
    const lower = turnText.toLowerCase()
    let firstPos = -1
    for (const kw of keywords) {
      const pos = lower.indexOf(kw)
      if (pos !== -1 && (firstPos === -1 || pos < firstPos)) firstPos = pos
    }
    const center = firstPos === -1 ? 0 : firstPos
    const start = Math.max(0, center - 80)
    const end   = Math.min(turnText.length, start + windowSize)
    const s     = Math.max(0, end - windowSize)
    return { segments: buildSegments(turnText.slice(s, end), keywords), prefix: s > 0, suffix: end < turnText.length }
  }

  let occurrences   = []
  let loadingOcc    = false
  let occNodeId     = null   // prevents stale responses overwriting newer selection

  async function findOccurrences(node) {
    const targetId = node?.id
    occurrences  = []
    loadingOcc   = true
    occNodeId    = targetId

    const convRefs = node?.conversations?.length
      ? node.conversations
      : node?.conversation_id ? [{ id: node.conversation_id, title: node.conversation_title ?? '', date: node.date }] : []

    if (!convRefs.length) { loadingOcc = false; return }

    const { unigrams, bigrams } = extractTerms(node.text_long ?? node.text ?? '')
    if (!unigrams.length) { loadingOcc = false; return }

    const allConvs = await fetchConversations()

    const results = []
    const multiConv = convRefs.length > 1
    for (const ref of convRefs) {
      const conv = allConvs.find(c => c.id === ref.id)
      if (!conv?.turns?.length) continue
      for (let i = 0; i < conv.turns.length; i++) {
        const turn  = conv.turns[i]
        const lower = (turn.text ?? '').toLowerCase()

        const matchedBigrams  = bigrams.filter(bg => lower.includes(bg))
        const matchedUnigrams = unigrams.filter(kw => lower.includes(kw))

        let passes = false
        let highlightTerms = []

        if (bigrams.length > 0) {
          // Require at least one bigram phrase match — eliminates single-word false positives
          passes = matchedBigrams.length > 0
          if (passes) {
            // Highlight matched phrases; add unigrams not already covered by a phrase
            highlightTerms = [
              ...matchedBigrams,
              ...matchedUnigrams.filter(u => !matchedBigrams.some(bg => bg.includes(u))),
            ]
          }
        } else {
          // Single content word: require it to appear
          passes = matchedUnigrams.length >= unigrams.length
          highlightTerms = matchedUnigrams
        }

        if (!passes) continue
        const score = matchedBigrams.length * 2 + matchedUnigrams.length
        const { segments, prefix, suffix } = getExcerpt(turn.text, highlightTerms)
        results.push({
          convId:    ref.id,
          convTitle: ref.title ?? conv.title ?? '',
          turnIdx:   i,
          role:      turn.role,
          segments,
          prefix,
          suffix,
          score,
          multiConv,
        })
      }
    }

    results.sort((a, b) => a.turnIdx - b.turnIdx || (b.score - a.score))
    if (occNodeId === targetId) {
      occurrences = results
      loadingOcc  = false
    }
  }

  $: if ($selectedItem?.type === 'belief') {
    findOccurrences($selectedItem.data)
  } else {
    occurrences = []
    loadingOcc  = false
  }
</script>

{#if $selectedItem}
  <aside class="panel">
    <button class="close" on:click={() => selectedItem.set(null)}>✕</button>

    {#if $selectedItem.type === 'topic'}
      {@const d = $selectedItem.data}
      <div class="tag cluster" style="background:{d.cluster_id === -1 ? 'var(--cluster-noise)' : `var(--cluster-${d.cluster_id})`}">
        {d.topic_label ?? 'Unclustered'}
      </div>
      <h2>{d.title}</h2>
      <p class="date">{fmt(d.timestamp)}</p>
      <div class="stats-row">
        <span>{d.human_turn_count} human turns</span>
        <span>{d.ai_turn_count} AI turns</span>
        <span>{d.duration_minutes < 1 ? '< 1 min' : Math.round(d.duration_minutes) + ' min'}</span>
      </div>
      <div class="transcript">
        {#each parseTurns(d.human_text).slice(0, 6) as turn}
          <div class="turn {turn.sender}">
            <span class="sender">{turn.sender === 'human' ? 'You' : 'Claude'}</span>
            <p>{turn.text.slice(0, 400)}{turn.text.length > 400 ? '…' : ''}</p>
          </div>
        {/each}
        {#if parseTurns(d.human_text).length > 6}
          <p class="more">+ {parseTurns(d.human_text).length - 6} more turns</p>
        {/if}
      </div>

    {:else if $selectedItem.type === 'method'}
      {@const d = $selectedItem.data}
      <h2>{d.title}</h2>
      <p class="date">{fmt(d.date)}</p>
      {#if d.workflow_summary}
        <p class="summary">{d.workflow_summary}</p>
      {/if}
      {#if d.method_spans?.length}
        {@const groups = [...d.method_spans.reduce((m, s) => {
          if (!m.has(s.label)) m.set(s.label, [])
          m.get(s.label).push(s.span)
          return m
        }, new Map()).entries()]}
        {#each groups as [label, texts]}
          <div class="section-label">{label}</div>
          <div class="kw-list">
            {#each [...new Set(texts)] as t}
              <span class="chip">{t}</span>
            {/each}
          </div>
        {/each}
      {:else}
        <p class="date">No methods extracted yet.</p>
      {/if}

    {:else if $selectedItem.type === 'belief'}
      {@const d = $selectedItem.data}
      <div class="badge-row">
        {#if d.origin}
          <div class="tag" style="background:{ORIGIN_COLOR[d.origin] ?? '#555'}">
            {ORIGIN_LABEL[d.origin] ?? d.origin}
          </div>
        {/if}
        <div class="tag tag-type" style="background:{TYPE_COLOR[d.type] ?? '#cbd5e1'}">
          {@html typeShapeSvg(d.type, TYPE_COLOR[d.type])}
          {d.type}
        </div>
      </div>
      <h2 class="belief-text">"{d.texts?.get?.(d.id) ?? d.text}"</h2>

      <div class="belief-meta">
        <span class="meta-item">
          <span class="meta-label">First appeared</span>
          <span>{fmt(d.firstDate ?? d.date)}</span>
        </span>
        <span class="meta-item">
          <span class="meta-label">Frequency</span>
          <span>Appeared in {d.frequency ?? 1} conversation{(d.frequency ?? 1) === 1 ? '' : 's'}</span>
        </span>
      </div>

      {#if d.conversations?.length}
        <div class="section-label">Recent Conversations</div>
        <ul class="conv-list">
          {#each d.conversations.slice().sort((a, b) => (b.date ?? '').localeCompare(a.date ?? '')).slice(0, 5) as c}
            <li>
              <span class="conv-title">{c.title || '(untitled)'}</span>
              {#if c.date}<span class="conv-date">{fmt(c.date)}</span>{/if}
            </li>
          {/each}
        </ul>
      {/if}

      {#if d._edges?.length}
        <div class="section-label">Connections</div>
        <div class="edge-list">
          {#each d._edges.filter(e => e.direction === 'out') as e}
            <div class="edge-item">
              <span class="edge-dir edge-out">↗</span>
              <span class="edge-chip edge-chip-{e.relation}">{e.relation}</span>
              {#if e.relation === 'supports' && e.scheme && SCHEME_LABEL[e.scheme]}
                <span class="edge-sub">{SCHEME_LABEL[e.scheme]}</span>
              {:else if e.relation === 'tension' && e.attack_type}
                <span class="edge-sub">{e.attack_type}</span>
              {/if}
              <span class="edge-peer">{e.peerText.length > 40 ? e.peerText.slice(0, 40) + '…' : e.peerText}</span>
            </div>
          {/each}
          {#each d._edges.filter(e => e.direction === 'in') as e}
            <div class="edge-item">
              <span class="edge-dir edge-in">↙</span>
              <span class="edge-chip edge-chip-{e.relation}">{e.relation}</span>
              {#if e.relation === 'supports' && e.scheme && SCHEME_LABEL[e.scheme]}
                <span class="edge-sub">{SCHEME_LABEL[e.scheme]}</span>
              {:else if e.relation === 'tension' && e.attack_type}
                <span class="edge-sub">{e.attack_type}</span>
              {/if}
              <span class="edge-peer">{e.peerText.length > 40 ? e.peerText.slice(0, 40) + '…' : e.peerText}</span>
            </div>
          {/each}
        </div>
      {/if}

      {#if loadingOcc || occurrences.length > 0}
        <div class="section-label">In Conversation</div>
        {#if loadingOcc}
          <div class="occ-searching">Searching…</div>
        {:else}
          <div class="occ-list">
            {#each occurrences as occ, i}
              <div class="occ-item">
                <div class="occ-header">
                  <span class="occ-role occ-role-{occ.role}">{occ.role === 'human' ? 'You' : 'Claude'}</span>
                  <span class="occ-turn">turn {occ.turnIdx + 1}</span>
                  {#if occ.multiConv}
                    <span class="occ-conv-label">{occ.convTitle.length > 22 ? occ.convTitle.slice(0,22)+'…' : occ.convTitle}</span>
                  {/if}
                </div>
                <div class="occ-text">
                  {#if occ.prefix}<span class="occ-ellipsis">…</span>{/if}<!--
                  -->{#each occ.segments as seg}{#if seg.hl}<mark class="occ-mark">{seg.text}</mark>{:else}<span>{seg.text}</span>{/if}{/each}<!--
                  -->{#if occ.suffix}<span class="occ-ellipsis">…</span>{/if}
                </div>
              </div>
            {/each}
          </div>
        {/if}
      {/if}
    {/if}
  </aside>
{/if}

<style>
  aside {
    position: fixed;
    top: 0; right: 0;
    width: 340px;
    height: 100vh;
    background: var(--surface);
    border-left: 1px solid var(--border);
    padding: 52px 20px 20px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 12px;
    z-index: 100;
    animation: slide-in 0.2s ease;
  }
  @keyframes slide-in {
    from { transform: translateX(100%); opacity: 0; }
    to   { transform: translateX(0);   opacity: 1; }
  }
  .close {
    position: absolute;
    top: 14px; right: 16px;
    background: transparent;
    border: none;
    color: var(--text-muted);
    font-size: 1rem;
    cursor: pointer;
    padding: 4px 8px;
  }
  .close:hover { color: var(--text); }
  .badge-row { display: flex; gap: 6px; flex-wrap: wrap; }
  .tag {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #3a4060;
    width: fit-content;
  }
  .tag-type { opacity: 0.75; }
  .cluster { background: var(--accent-dim); }
  h2 { font-size: 1rem; font-weight: 600; line-height: 1.4; }
  .belief-text { font-style: italic; font-weight: 400; font-size: 0.95rem; }
  .date { font-size: 0.78rem; color: var(--text-muted); }
  .stats-row {
    display: flex;
    gap: 12px;
    font-size: 0.78rem;
    color: var(--text-muted);
  }
  .summary {
    font-size: 0.85rem;
    color: var(--text);
    line-height: 1.6;
    border-left: 2px solid var(--accent);
    padding-left: 10px;
  }
  .kw-list { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip {
    padding: 3px 10px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 999px;
    font-size: 0.75rem;
    color: var(--text-muted);
  }
  .transcript { display: flex; flex-direction: column; gap: 10px; }
  .turn { display: flex; flex-direction: column; gap: 3px; }
  .sender { font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-muted); }
  .turn.human .sender { color: var(--claim); }
  .turn p { font-size: 0.82rem; line-height: 1.5; color: var(--text); }
  .more { font-size: 0.78rem; color: var(--text-muted); text-align: center; }

  /* Belief node detail */
  .belief-meta {
    display: flex;
    flex-direction: column;
    gap: 5px;
    padding: 10px 12px;
    background: var(--surface2);
    border-radius: 8px;
    font-size: 0.78rem;
    color: var(--text-muted);
  }
  .meta-item { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
  .meta-label { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; }
  .section-label {
    font-size: 0.68rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-muted);
    margin-top: 2px;
  }
  .conv-list {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .conv-list li {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 8px;
    padding: 6px 10px;
    background: var(--surface2);
    border-radius: 6px;
    font-size: 0.78rem;
  }
  .conv-title { color: var(--text); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .conv-date  { color: var(--text-muted); font-size: 0.72rem; white-space: nowrap; flex-shrink: 0; }

  /* Type badge shape icon */
  .tag-type {
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }

  /* Edge connections */
  .edge-list {
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .edge-item {
    display: flex;
    align-items: baseline;
    gap: 6px;
    font-size: 0.78rem;
    padding: 5px 8px;
    background: var(--surface2);
    border-radius: 6px;
    flex-wrap: wrap;
  }
  .edge-dir {
    font-size: 0.75rem;
    flex-shrink: 0;
    opacity: 0.7;
  }
  .edge-out { color: #6bcb77; }
  .edge-in  { color: #94a3b8; }
  .edge-chip {
    padding: 1px 7px;
    border-radius: 999px;
    font-size: 0.68rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    flex-shrink: 0;
  }
  .edge-chip-supports { background: rgba(107,203,119,0.2); color: #2d6a3f; }
  .edge-chip-tension  { background: rgba(248,113,113,0.18); color: #9b1c1c; }
  .edge-sub {
    font-size: 0.7rem;
    color: var(--text-muted);
    font-style: italic;
    flex-shrink: 0;
  }
  .edge-peer {
    color: var(--text);
    line-height: 1.4;
    flex: 1;
    min-width: 0;
  }

  /* In-conversation occurrences */
  .occ-searching {
    font-size: 0.78rem;
    color: var(--text-muted);
    padding: 4px 0;
  }
  .occ-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .occ-item {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 7px;
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .occ-header {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .occ-role {
    font-size: 0.67rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 1px 7px;
    border-radius: 999px;
  }
  .occ-role-human    { background: rgba(240,233,222,0.8);  color: #3a4060; }
  .occ-role-assistant { background: rgba(169,186,171,0.45); color: #3a4060; }
  .occ-turn {
    font-size: 0.68rem;
    color: var(--text-muted);
  }
  .occ-conv-label {
    font-size: 0.66rem;
    color: var(--text-muted);
    margin-left: auto;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 110px;
    font-style: italic;
  }
  .occ-text {
    font-size: 0.79rem;
    line-height: 1.55;
    color: var(--text);
    word-break: break-word;
  }
  .occ-ellipsis {
    color: var(--text-muted);
    font-size: 0.82rem;
  }
  :global(.occ-mark) {
    background: rgba(250,204,21,0.38);
    border-radius: 2px;
    padding: 0 1px;
  }
</style>
