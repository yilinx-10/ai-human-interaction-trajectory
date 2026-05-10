<script>
  // @ts-nocheck
  import { beliefViewMode, beliefFocusedConvId, beliefEditMode, selectedItem } from '../../stores.js'

  export let conv = null

  function back() {
    beliefViewMode.set('global')
    beliefFocusedConvId.set(null)
    beliefEditMode.set('none')
    selectedItem.set(null)
  }

  function toggle(mode) {
    beliefEditMode.update(m => m === mode ? 'none' : mode)
  }
</script>

<div class="toolbar">
  {#if $beliefViewMode === 'conversation'}
    <button class="back" on:click={back}>← All Networks</button>

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
        class:active={$beliefEditMode === 'delete'}
        on:click={() => toggle('delete')}
        title="Click a node or edge to remove it"
      >Delete</button>
    </div>
  {:else}
    <span class="global-label">Networks</span>
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
  .global-label {
    font-size: 0.78rem;
    font-weight: 600;
    color: var(--text-muted);
    white-space: nowrap;
  }
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
  button:hover:not(.active) { border-color: var(--accent); color: var(--text); }
</style>
