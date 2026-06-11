/**
 * LifeReel AI - WeeklyRewindPage View
 */
import { intelApi } from '../api/api.js';
import { RewindCard } from '../components/RewindCard.js';

export class WeeklyRewindPage {
  constructor() {
    this.carousel = null;
    this.container = null;
  }

  render() {
    this.container = document.createElement('div');
    this.container.className = 'page-view rewind-container';
    
    this.container.innerHTML = `
      <div class="section-title-wrap" style="text-align: left; margin-bottom: 2rem;">
        <h2 class="section-title">Weekly Rewind</h2>
        <p class="section-subtitle">A cozy, slide-based recap of your recorded memories this week.</p>
      </div>

      <!-- Mount RewindCard Carousel -->
      <div id="carousel-mount">
        <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; width: 100%; padding: 4rem 0; gap: 1rem; color: var(--text-secondary);">
          <div class="spinner-ring" style="width: 40px; height: 40px; border-radius: 50%; border: 3px solid rgba(255, 255, 255, 0.05); border-top-color: #ff8da1; animation: spin 1s linear infinite;"></div>
          <p style="font-family: var(--font-tech); font-size: 0.9rem;">Gathering your weekly memories...</p>
        </div>
      </div>

      <!-- Dashboard Footer stats summary blocks -->
      <div class="rewind-footer-summary" id="stats-summary-footer">
        <!-- Stats populated dynamically below -->
      </div>
    `;

    return this.container;
  }

  async onMount() {
    try {
      const memories = await intelApi.getTimeline();
      
      const carouselMount = this.container.querySelector('#carousel-mount');
      if (carouselMount) {
        carouselMount.innerHTML = '';
        
        // Initialize slide deck
        this.carousel = new RewindCard(memories);
        carouselMount.appendChild(this.carousel.render());
        
        // Populate bottom summary blocks
        const footer = this.container.querySelector('#stats-summary-footer');
        if (footer) {
          const totals = this.carousel.totals;

          const lastNodeText = memories.length > 0
            ? `Entry: "${memories[0].title}" was saved as your latest memory.`
            : 'No memories saved yet.';

          const stabilityText = memories.length <= 1
            ? 'Start adding memories to unlock mood analytics.'
            : `Balanced around "${totals.dominantMood}". You are doing great!`;

          footer.innerHTML = `
            <div class="recap-block-card">
              <div class="recap-icon-bubble"><i class="bi bi-clock-history"></i></div>
              <div class="recap-info-pane">
                <h4>Total Recording Time</h4>
                <p>${totals.totalDuration} seconds of voice recordings saved.</p>
              </div>
            </div>

            <div class="recap-block-card">
              <div class="recap-icon-bubble"><i class="bi bi-shield-check"></i></div>
              <div class="recap-info-pane">
                <h4>Calmness Index</h4>
                <p>${stabilityText}</p>
              </div>
            </div>

            <div class="recap-block-card">
              <div class="recap-icon-bubble"><i class="bi bi-check-all"></i></div>
              <div class="recap-info-pane">
                <h4>Latest Entry</h4>
                <p>${lastNodeText}</p>
              </div>
            </div>
          `;
        }
      }
    } catch (err) {
      console.error("Failed to load weekly rewind:", err);
      const carouselMount = this.container.querySelector('#carousel-mount');
      if (carouselMount) {
        carouselMount.innerHTML = `
          <div class="empty-timeline-msg" style="color: #ff5572; border-color: rgba(255, 85, 114, 0.15);">
            <i class="bi bi-exclamation-triangle" style="font-size: 2rem; display: block; margin-bottom: 0.5rem;"></i>
            Failed to load weekly rewind recap.
          </div>
        `;
      }
    }
  }

  destroy() {
    if (this.carousel) {
      this.carousel.destroy();
    }
  }
}
