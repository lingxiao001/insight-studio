import { useEffect, useRef, useState } from 'react';
import { ChartNoAxesCombined, LoaderCircle } from 'lucide-react';
import type { Chart } from './types';
const palette = ['#7e5555', '#6e8077', '#9b8b6f', '#71818a', '#9a7f88', '#8c8c6c', '#a07857'];
let plotlyPromise: Promise<any> | undefined;
function getPlotly() { return plotlyPromise ??= import('plotly.js-dist-min').then((module) => module.default || module); }
export default function Plot({ chart }: { chart: Chart }) {
  const element = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  useEffect(() => {
    let disposed = false;
    let plotly: any;
    let observer: ResizeObserver | undefined;
    const host = element.current;
    setLoading(true); setError(false);
    getPlotly().then(async (Plotly) => {
      if (disposed || !host) return;
      plotly = Plotly;
      const data = chart.figure.data.map((trace, index) => {
        const base = { ...trace };
        if (trace.type === 'heatmap') base.colorscale = [[0, '#778d99'], [0.5, '#f1eee7'], [1, '#8b5055']];
        else if (trace.type === 'pie') base.marker = { ...trace.marker, colors: palette };
        else {
          if (typeof trace.marker?.color !== 'object') base.marker = { ...trace.marker, color: palette[index % palette.length] };
          base.line = { ...trace.line, color: palette[index % palette.length] };
          if (trace.fill) base.fillcolor = 'rgba(126,85,85,.07)';
          if (trace.type === 'box') base.fillcolor = 'rgba(126,85,85,.12)';
        }
        if (trace.type === 'heatmap') base.colorbar = { ...trace.colorbar, tickfont: { color: '#625f59', size: 11 }, outlinewidth: 0, title: { ...trace.colorbar?.title, font: { color: '#625f59' } } };
        return base;
      });
      const layout = {
        ...chart.figure.layout,
        title: undefined, template: {}, autosize: true, width: undefined, height: window.innerWidth < 480 ? 330 : 340, paper_bgcolor: '#fffdf9', plot_bgcolor: '#fffdf9',
        colorway: palette, font: { family: '"Helvetica Neue", "PingFang SC", sans-serif', size: 12, color: '#625f59' },
        margin: { l: 58, r: 28, t: 22, b: 65 },
        hoverlabel: { bgcolor: '#fffdf9', bordercolor: '#bdb5a7', font: { family: '"Helvetica Neue", "PingFang SC", sans-serif', color: '#393630', size: 12 } },
        annotations: chart.figure.layout.annotations?.map((note: Record<string, any>) => ({ ...note, font: { ...note.font, color: '#625f59' } })),
        coloraxis: { ...chart.figure.layout.coloraxis, colorbar: { ...chart.figure.layout.coloraxis?.colorbar, tickfont: { color: '#625f59' }, outlinewidth: 0 } },
        xaxis: { ...chart.figure.layout.xaxis, automargin: true, gridcolor: '#e4e0d8', zerolinecolor: '#cdc6ba', linecolor: '#c8c0b4', tickcolor: '#c8c0b4', tickfont: { color: '#686157', size: 11 }, title: { ...chart.figure.layout.xaxis?.title, font: { color: '#625b51', size: 12 } } },
        yaxis: { ...chart.figure.layout.yaxis, automargin: true, gridcolor: '#e4e0d8', zerolinecolor: '#cdc6ba', linecolor: '#c8c0b4', tickcolor: '#c8c0b4', tickfont: { color: '#686157', size: 11 }, title: { ...chart.figure.layout.yaxis?.title, font: { color: '#625b51', size: 12 } } },
        legend: { ...chart.figure.layout.legend, orientation: 'h', y: -0.22, x: 0, bgcolor: 'transparent', font: { color: '#625f59', size: 11 } },
      };
      await Plotly.newPlot(host, data, layout, { responsive: true, displaylogo: false, modeBarButtonsToRemove: ['lasso2d', 'select2d', 'sendDataToCloud'], toImageButtonOptions: { format: 'png', filename: chart.title, scale: 2 } });
      if (disposed) { Plotly.purge(host); return; }
      setLoading(false);
      observer = new ResizeObserver(() => { if (!disposed) Plotly.Plots.resize(host); });
      observer.observe(host);
    }).catch(() => { if (!disposed) { setError(true); setLoading(false); } });
    return () => { disposed = true; observer?.disconnect(); if (plotly && host) plotly.purge(host); };
  }, [chart]);
  return <div className="plot-shell">
    {loading && <div className="plot-state"><LoaderCircle aria-hidden="true" className="spin" size={21} /><span>正在绘制图表…</span></div>}
    {error && <div className="plot-state"><ChartNoAxesCombined aria-hidden="true" size={25} /><span>图表暂时无法绘制，请刷新重试</span></div>}
    <div ref={element} className="plot" style={{ visibility: loading || error ? 'hidden' : 'visible' }} />
  </div>;
}
