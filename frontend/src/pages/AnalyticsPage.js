/**
 * LifeReel AI - AnalyticsPage View
 */
import { intelApi } from '../api/api.js';
import { analyticsChart } from '../components/AnalyticsChart.js';

export class AnalyticsPage {
  constructor() {
    this.container = null;
  }

  render() {
    this.container = document.createElement('div');
    this.container.className = 'page-view';

    this.container.innerHTML = `
      <div class="section-title-wrap" style="text-align: left; margin-bottom: 3.5rem;">
        <h2 class="section-title">Mood Tracker & Analytics</h2>
        <p class="section-subtitle">A cozy overview of your moods, calmness index, and daily highlights.</p>
      </div>

      <div class="analytics-dashboard-grid">
        <!-- Card 1: Trend line graph -->
        <div class="analytics-card" id="trend-card-mount">
          <div class="analytics-header-row">
            <div class="analytics-title-box">
              <h3>Weekly Mood Trends</h3>
              <p>See how your moods have changed over the last week.</p>
            </div>
            <span class="analytics-badge">Mood Chart</span>
          </div>
          <div style="display: flex; align-items: center; justify-content: center; height: 180px;" class="analytics-loading-placeholder">
            <div class="spinner-ring" style="width: 30px; height: 30px; border-radius: 50%; border: 3px solid rgba(255, 255, 255, 0.05); border-top-color: #ff8da1; animation: spin 1s linear infinite;"></div>
          </div>
        </div>

        <!-- Card 2: circular gauge -->
        <div class="analytics-card" id="gauge-card-mount">
          <div class="analytics-header-row">
            <div class="analytics-title-box">
              <h3>Calmness Score</h3>
              <p>A score showing how calm and relaxed you are.</p>
            </div>
            <span class="analytics-badge">Current Level</span>
          </div>
          <div style="display: flex; align-items: center; justify-content: center; height: 180px;" class="analytics-loading-placeholder">
            <div class="spinner-ring" style="width: 30px; height: 30px; border-radius: 50%; border: 3px solid rgba(255, 255, 255, 0.05); border-top-color: #ff8da1; animation: spin 1s linear infinite;"></div>
          </div>
        </div>

        <!-- Card 3: Cognitive insights -->
        <div class="analytics-card full-width">
          <div class="analytics-header-row" style="margin-bottom: 1.5rem;">
            <div class="analytics-title-box">
              <h3>Cozy AI Insights</h3>
              <p>Reflections and tips based on your recent journal entries.</p>
            </div>
            <span class="analytics-badge"><i class="bi bi-stars"></i> AI Insights</span>
          </div>
          
          <div class="insights-pane-wrap">
            <div class="insight-item-box">
              <div class="insight-icon-ring"><i class="bi bi-clock-history"></i></div>
              <div class="insight-text-area">
                <h5>Reflective Moments</h5>
                <p>You tend to reflect on sweet past moments in the middle of the week. Thinking about warm memories is a lovely way to unwind and feel anchored!</p>
              </div>
            </div>
            <div class="insight-item-box">
              <div class="insight-icon-ring" style="color: var(--color-blue); background: rgba(0, 240, 255, 0.08); border-color: rgba(0, 240, 255, 0.2);"><i class="bi bi-heart-pulse"></i></div>
              <div class="insight-text-area">
                <h5>Calming Rhythm</h5>
                <p>Your average calmness score is around 84%. Recording your thoughts at sunset is a wonderful way to relax and let go of the day's stress.</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;

    return this.container;
  }

  async onMount() {
    try {
      const memories = await intelApi.getTimeline();
      
      // Determine stability score
      let score = 84;
      if (memories.length > 0) {
        // Scale dynamic score slightly based on logs count
        score = Math.min(96, 75 + memories.length * 3);
      }

      // Remove loading placeholders
      this.container.querySelectorAll('.analytics-loading-placeholder').forEach(p => p.remove());

      // Mount SVG components
      const trendMount = this.container.querySelector('#trend-card-mount');
      if (trendMount) {
        trendMount.appendChild(analyticsChart.renderTrendLine(memories));
      }
      
      const gaugeMount = this.container.querySelector('#gauge-card-mount');
      if (gaugeMount) {
        gaugeMount.appendChild(analyticsChart.renderGauge(score));
      }
    } catch (err) {
      console.error("Failed to load analytics:", err);
      this.container.querySelectorAll('.analytics-loading-placeholder').forEach(p => {
        p.innerHTML = `<span style="color: #ff5572; font-size: 0.85rem;"><i class="bi bi-exclamation-circle"></i> Error loading data</span>`;
      });
    }
  }
}
