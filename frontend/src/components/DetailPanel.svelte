<script>
  // @ts-nocheck  — data nodes come from dynamic JSON; type safety via logic, not annotations
  import { selectedItem } from '../stores.js'

  const TYPE_COLOR = {
    claim: 'var(--claim)',
    assumption: 'var(--assumption)',
    conclusion: 'var(--conclusion)',
  }

  const ORIGIN_COLOR = { user: '#2dd4bf', model: '#f87171', 'co-constructed': '#a78bfa' }
  const ORIGIN_LABEL = { user: 'User-introduced', model: 'Model-introduced', 'co-constructed': 'Co-constructed' }

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
        <div class="tag tag-type" style="background:{TYPE_COLOR[d.type] ?? '#555'}">
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
    color: #fff;
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
</style>
