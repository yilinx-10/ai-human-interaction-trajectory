<script>
  // @ts-nocheck
  import * as d3 from 'd3';
  import { onMount, onDestroy } from 'svelte';

  export let data = [];     // flat list with `date` field (YYYY-MM-DD)
  export let range = null;  // [Date, Date] | null — two-way bound

  let svgEl;
  let brushG;
  const H = 64;
  let W = 1000;
  const margin = { top: 6, right: 16, bottom: 28, left: 16 };

  let dates = [];
  let xScale = null;
  let yScale = null;
  let bins = [];
  let brush;

  function rebuild() {
    dates = (data || [])
      .filter(d => d.date)
      .map(d => new Date(d.date))
      .filter(d => !isNaN(d.getTime()));
    if (!dates.length) return;
    const extent = d3.extent(dates);
    xScale = d3.scaleTime().domain(extent).range([margin.left, W - margin.right]);
    const weeks = d3.timeWeek.range(extent[0], d3.timeWeek.offset(extent[1], 1));
    bins = d3.bin().domain(xScale.domain()).thresholds(weeks)(dates);
    yScale = d3.scaleLinear()
      .domain([0, d3.max(bins, b => b.length) || 1])
      .range([H - margin.bottom, margin.top]);
  }

  function rebuildBrush() {
    if (!brushG || !xScale) return;
    brush = d3.brushX()
      .extent([[margin.left, margin.top], [W - margin.right, H - margin.bottom]])
      .on('brush end', ev => {
        if (!ev.selection) { range = null; return; }
        const [x0, x1] = ev.selection;
        range = [xScale.invert(x0), xScale.invert(x1)];
      });
    d3.select(brushG).call(brush);
  }

  function onResize() {
    W = (window.innerWidth || 1200) - 1;
    rebuild();
    rebuildBrush();
  }

  onMount(() => { onResize(); window.addEventListener('resize', onResize); });
  onDestroy(() => window.removeEventListener('resize', onResize));

  $: if (data) rebuild();
  $: ticks = xScale ? xScale.ticks(6) : [];
  const monDayFmt = d3.timeFormat('%b %d');
  const yearFmt   = d3.timeFormat('%Y');
</script>

<div class="time-brush">
  <svg width={W} height={H} bind:this={svgEl}>
    {#each bins as b}
      {@const x = xScale ? xScale(b.x0) : 0}
      {@const w = xScale ? Math.max(1, xScale(b.x1) - xScale(b.x0) - 1) : 0}
      {@const y = yScale ? yScale(b.length) : 0}
      {@const bh = yScale ? (H - margin.bottom) - yScale(b.length) : 0}
      <rect {x} {y} width={w} height={bh} fill="#a08bb8" opacity="0.75" rx="1" />
    {/each}

    <line
      x1={margin.left} x2={W - margin.right}
      y1={H - margin.bottom} y2={H - margin.bottom}
      stroke="#bbb" stroke-width="0.5"
    />

    {#if xScale}
      {#each ticks as t}
        <text x={xScale(t)} y={H - 16} text-anchor="middle" font-size="10" fill="#555">
          {monDayFmt(t)}
        </text>
        <text x={xScale(t)} y={H - 3} text-anchor="middle" font-size="9" fill="#999">
          {yearFmt(t)}
        </text>
      {/each}
    {/if}

    <g bind:this={brushG} class="brush" />
  </svg>
</div>

<style>
  .time-brush {
    border-bottom: 1px solid #eee;
    background: #fafafa;
    flex-shrink: 0;
    user-select: none;
  }
  :global(.brush .selection) {
    fill: rgba(160, 139, 184, 0.15);
    stroke: rgba(160, 139, 184, 0.5);
    stroke-width: 1;
    shape-rendering: crispEdges;
  }
  :global(.brush .handle) { display: none; }
  :global(.brush .overlay) { cursor: crosshair; }
</style>
