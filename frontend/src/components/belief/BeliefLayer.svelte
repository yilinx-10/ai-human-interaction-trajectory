<script>
  import { onMount } from 'svelte'
  import { beliefData, beliefViewMode, beliefFocusedConvId } from '../../stores.js'
  import { buildMergedGraph } from '../../lib/beliefUtils.js'
  import ForceGraph from './ForceGraph.svelte'
  import DateRangeSlider from './DateRangeSlider.svelte'
  import BeliefLegend from './BeliefLegend.svelte'
  import BeliefEditToolbar from './BeliefEditToolbar.svelte'
  let loading = true
  let error = null

  onMount(async () => {
    if ($beliefData !== null) { loading = false; return }
    try {
      const res = await fetch('/data/layer_belief.json')
      if (!res.ok) throw new Error(res.statusText)
      beliefData.set(await res.json())
    } catch (e) {
      error = e.message
    } finally {
      loading = false
    }
  })

  $: merged     = $beliefData ? buildMergedGraph($beliefData.per_conversation) : null
  $: focusedConv = $beliefData?.per_conversation.find(c => c.id === $beliefFocusedConvId) ?? null
</script>

<div class="layer">
  {#if loading}
    <div class="loading">Loading belief network…</div>
  {:else if error}
    <div class="error">{error}</div>
  {:else if merged}
    <BeliefEditToolbar conv={focusedConv} />

    <ForceGraph
      nodes={merged.nodes}
      edges={merged.edges}
      perConversation={$beliefData.per_conversation}
      idToCanon={merged.idToCanon}
    />

    <BeliefLegend />

    {#if $beliefViewMode === 'global'}
      <DateRangeSlider />
      <div class="stats-bar">
        <span>{merged.nodes.length} beliefs</span>
        <span class="sep">·</span>
        <span>{merged.edges.length} connections</span>
        <span class="sep">·</span>
        <span class="shared">{merged.nodes.filter(n => n.shared).length} shared</span>
        <span class="sep">·</span>
        <span class="contra">{merged.edges.filter(e => e.relation === 'tension').length} tensions</span>
      </div>
    {/if}
  {/if}
</div>

<style>
  .layer { position: relative; width: 100%; height: 100%; }

  .stats-bar {
    position: absolute;
    bottom: 16px;
    left: 50%;
    transform: translateX(-50%);
    display: flex;
    align-items: center;
    gap: 8px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 5px 18px;
    font-size: 0.72rem;
    color: var(--text-muted);
    pointer-events: none;
    z-index: 10;
    white-space: nowrap;
  }
  .stats-bar .sep    { opacity: 0.4; }
  .stats-bar .shared { color: #6366f1; }
  .stats-bar .contra { color: var(--contradictory); }
</style>
