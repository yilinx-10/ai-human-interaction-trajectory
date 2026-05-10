<script>
  import './styles/global.css'
  import { activeLayer } from './stores.js'
  import LayerSwitcher from './components/LayerSwitcher.svelte'
  import DetailPanel from './components/DetailPanel.svelte'
  import TopicLayer from './components/topic/TopicLayer.svelte'
  import MethodLayer from './components/method/MethodLayer.svelte'
  import BeliefLayer from './components/belief/BeliefLayer.svelte'
</script>

<header>
  <div class="title">
    <span class="wordmark">ChatTrajectory</span>
    <span class="subtitle">AI conversation history explorer</span>
  </div>
  <LayerSwitcher />
</header>

<main>
  {#if $activeLayer === 'topic'}
    <TopicLayer />
  {:else if $activeLayer === 'method'}
    <MethodLayer />
  {:else if $activeLayer === 'belief'}
    <BeliefLayer />
  {/if}
</main>

<DetailPanel />

<style>
  :global(body) { overflow: hidden; }
  :global(#app) { display: flex; flex-direction: column; height: 100vh; }

  header { flex-shrink: 0; background: var(--surface); }

  .title {
    display: flex;
    align-items: baseline;
    gap: 10px;
    padding: 14px 16px 0;
  }
  .wordmark { font-size: 1.1rem; font-weight: 700; letter-spacing: -0.02em; }
  .subtitle { font-size: 0.75rem; color: var(--text-muted); }

  main { flex: 1; overflow: hidden; position: relative; }
</style>
