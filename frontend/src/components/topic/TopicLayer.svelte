<script>
  import { onMount } from 'svelte'
  import { topicData } from '../../stores.js'
  import BubbleMap from './BubbleMap.svelte'
  import TimeBrush from './TimeBrush.svelte'

  let loading = true
  let error = null
  let timeRange = null  // [Date, Date] | null

  // Normalise: old format = flat array, new format = { conversations, tree }
  $: conversations = Array.isArray($topicData)
    ? $topicData
    : ($topicData?.conversations ?? [])

  $: tree = Array.isArray($topicData) ? null : ($topicData?.tree ?? null)

  onMount(async () => {
    if ($topicData !== null) { loading = false; return }
    try {
      const res = await fetch('/data/layer_topic.json')
      if (!res.ok) throw new Error(res.statusText)
      topicData.set(await res.json())
    } catch (e) {
      error = e.message
    } finally {
      loading = false
    }
  })
</script>

<div class="layer">
  {#if loading}
    <div class="loading">Loading conversations…</div>
  {:else if error}
    <div class="error">{error}</div>
  {:else}
    <TimeBrush data={conversations} bind:range={timeRange} />
    <div class="map-wrap">
      <BubbleMap data={conversations} {tree} {timeRange} />
    </div>
  {/if}
</div>

<style>
  .layer { width: 100%; height: 100%; display: flex; flex-direction: column; }
  .map-wrap { flex: 1; overflow: hidden; position: relative; }
  .loading, .error { padding: 16px; color: var(--text-muted); }
  .error { color: #c00; }
</style>
