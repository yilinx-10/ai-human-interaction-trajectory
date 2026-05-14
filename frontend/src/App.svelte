<script>
  // @ts-nocheck
  import './styles/global.css'
  import {
    expandedConvId, bubbleOrigin,
    beliefFocusedConvId, beliefViewMode,
  } from './stores.js'
  import DetailPanel from './components/DetailPanel.svelte'
  import TopicLayer from './components/topic/TopicLayer.svelte'
  import BeliefLayer from './components/belief/BeliefLayer.svelte'

  // When a conversation is expanded, sync belief stores into conversation mode
  $: if ($expandedConvId) {
    beliefFocusedConvId.set($expandedConvId)
    beliefViewMode.set('conversation')
  }
</script>

<header>
  <div class="title">
    <span class="wordmark">ChatTrajectory</span>
    <span class="subtitle">AI conversation history explorer</span>
  </div>
</header>

<main>
  <!-- Topic view stays mounted to preserve bubble expansion state -->
  <div class="topic-view" class:hidden={!!$expandedConvId}>
    <TopicLayer />
  </div>

  {#if $expandedConvId}
    <!-- Network view: expands from the clicked bubble via clip-circle animation -->
    <div
      class="belief-view"
      style="--ox:{$bubbleOrigin?.x ?? 50}px; --oy:{$bubbleOrigin?.y ?? 50}px"
    >
      <BeliefLayer />
    </div>
  {/if}
</main>

<DetailPanel />

<style>
  :global(body) { overflow: hidden; }
  :global(#app) { display: flex; flex-direction: column; height: 100vh; }

  header {
    flex-shrink: 0;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 14px 16px;
  }

  .title {
    display: flex;
    align-items: baseline;
    gap: 10px;
  }
  .wordmark { font-size: 1.1rem; font-weight: 700; letter-spacing: -0.02em; }
  .subtitle { font-size: 0.75rem; color: var(--text-muted); }

  main { flex: 1; overflow: hidden; position: relative; }

  .topic-view {
    position: absolute;
    inset: 0;
  }
  .topic-view.hidden {
    visibility: hidden;
    pointer-events: none;
  }

  /* Belief network expands via a clip-circle from the clicked bubble position */
  .belief-view {
    position: absolute;
    inset: 0;
    animation: circle-expand 0.42s cubic-bezier(0.4, 0, 0.2, 1) forwards;
  }

  @keyframes circle-expand {
    from { clip-path: circle(0px at var(--ox) var(--oy)); }
    to   { clip-path: circle(200% at var(--ox) var(--oy)); }
  }
</style>
