<script>
  // @ts-nocheck
  import { beliefViewMode, beliefFocusedConvId, beliefEditMode, selectedItem, expandedConvId } from '../../stores.js'

  export let conv = null

  function back() {
    expandedConvId.set(null)
    beliefFocusedConvId.set(null)
    beliefViewMode.set('global')
    beliefEditMode.set('none')
    selectedItem.set(null)
  }

  function toggle(mode) {
    beliefEditMode.update(m => m === mode ? 'none' : mode)
  }
</script>

<div class="toolbar">
  {#if $beliefViewMode === 'conversation'}
    <button class="back" on:click={back}>← Topic Map</button>

    {#if conv}
      <span class="divider"></span>
      <span class="conv-title" title={conv.title}>{conv.title}</span>
    {/if}

    <span class="spacer"></span>

    <div class="actions">
      <button
        class:active={$beliefEditMode === 'addNode'}
        on:click={() => toggle('addNode')}
        title="Double-click the canvas to add a node"
      >+ Node</button>
      <button
        class:active={$beliefEditMode === 'addEdge'}
        on:click={() => toggle('addEdge')}
        title="Click two nodes to connect them"
      >+ Edge</button>
      <button
        class:active={$beliefEditMode === 'merge'}
        on:click={() => toggle('merge')}
        title="Click two nodes to merge them into one"
        class:merge-btn={true}
      >Merge</button>
      <button
        class:active={$beliefEditMode === 'delete'}
        on:click={() => toggle('delete')}
        title="Click a node or edge to remove it"
        class:delete-btn={true}
      >Delete</button>
    </div>
  {:else}
    <span class="global-badge">
      <svg class="globe-icon" width="13" height="13" viewBox="0 0 13 13" fill="none">
        <circle cx="6.5" cy="6.5" r="5.5" stroke="currentColor" stroke-width="1.2"/>
        <ellipse cx="6.5" cy="6.5" rx="2.4" ry="5.5" stroke="currentColor" stroke-width="1.2"/>
        <line x1="1" y1="6.5" x2="12" y2="6.5" stroke="currentColor" stroke-width="1.2"/>
      </svg>
      All Conversations
    </span>
    <span class="spacer"></span>
    <div class="actions">
      <button
        class:active={$beliefEditMode === 'addEdge'}
        on:click={() => toggle('addEdge')}
        title="Click a node in one network, then a node in another to link them"
      >+ Link Networks</button>
    </div>
  {/if}
</div>

<style>
  .toolbar {
    position: absolute;
    top: 12px; left: 12px;
    z-index: 20;
    display: flex;
    align-items: center;
    gap: 10px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 7px 14px;
    font-size: 0.82rem;
    max-width: calc(100% - 380px);
    overflow: hidden;
  }
  .back {
    background: transparent;
    border: none;
    color: var(--accent);
    cursor: pointer;
    font-size: 0.82rem;
    padding: 0;
    font-weight: 600;
    white-space: nowrap;
    flex-shrink: 0;
  }
  .back:hover { text-decoration: underline; }
  .divider { width: 1px; height: 16px; background: var(--border); flex-shrink: 0; }
  .conv-title {
    color: var(--text);
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex-shrink: 1;
    min-width: 0;
  }
  .global-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 0.8rem;
    font-weight: 700;
    color: var(--accent);
    background: color-mix(in srgb, var(--accent) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent) 28%, transparent);
    border-radius: 5px;
    padding: 2px 9px 2px 7px;
    white-space: nowrap;
    letter-spacing: -0.01em;
  }
  .globe-icon { flex-shrink: 0; }
  .spacer { flex: 1; min-width: 8px; }
  .actions { display: flex; gap: 6px; flex-shrink: 0; }
  button {
    padding: 4px 10px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 5px;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 0.78rem;
    transition: all 0.15s;
    white-space: nowrap;
  }
  button.active {
    background: var(--accent);
    border-color: var(--accent);
    color: #fff;
  }
  button.merge-btn.active {
    background: #b45309;
    border-color: #b45309;
  }
  button.delete-btn.active {
    background: #dc2626;
    border-color: #dc2626;
  }
  button:hover:not(.active) { border-color: var(--accent); color: var(--text); }
</style>
