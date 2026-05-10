<script>
  import { activeLayer } from '../stores.js'

  const layers = [
    { id: 'topic',  label: 'What',   sub: 'Topics & clusters' },
    { id: 'method', label: 'How',    sub: 'Methods over time' },
    { id: 'belief', label: 'Why',    sub: 'Belief networks' },
  ]
</script>

<nav>
  {#each layers as l}
    <button
      class:active={$activeLayer === l.id}
      on:click={() => activeLayer.set(l.id)}
    >
      <span class="label">{l.label}</span>
      <span class="sub">{l.sub}</span>
    </button>
  {/each}
</nav>

<style>
  nav {
    display: flex;
    gap: 4px;
    padding: 12px 16px 0;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
  }
  button {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
    padding: 8px 20px;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--text-muted);
    cursor: pointer;
    transition: color 0.15s, border-color 0.15s;
    margin-bottom: -1px;
  }
  button:hover { color: var(--text); }
  button.active {
    color: var(--text);
    border-bottom-color: var(--accent);
  }
  .label { font-weight: 600; font-size: 0.95rem; }
  .sub   { font-size: 0.72rem; color: inherit; opacity: 0.65; }
</style>
