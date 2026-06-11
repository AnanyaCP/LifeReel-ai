/**
 * LifeReel AI - ProfilePage View
 */
import { auth } from '../utils/auth.js';
import { intelApi } from '../api/api.js';
import { MemoryCard } from '../components/MemoryCard.js';

export class ProfilePage {
  constructor() {
    this.container = null;
  }

  render() {
    this.container = document.createElement('div');
    this.container.className = 'page-view profile-container';

    const user = auth.getCurrentUser();
    if (!user) {
      setTimeout(() => { window.location.hash = '#login'; }, 50);
      return this.container;
    }

    this.container.innerHTML = `
      <div class="profile-card">
        <div class="profile-avatar-wrap">
          <img src="${user.avatar}" alt="${user.username} Avatar">
        </div>
        
        <div class="profile-details">
          <span style="color: var(--color-orange); text-transform: uppercase; font-family: var(--font-tech); font-weight: 700; letter-spacing: 2px; font-size: 0.8rem;">User Profile</span>
          <h2>${user.username}</h2>
          <p style="margin-top: 0.25rem;"><i class="bi bi-envelope" style="margin-right: 0.5rem;"></i>${user.email}</p>
          <p><i class="bi bi-calendar-check" style="margin-right: 0.5rem;"></i>Diary Started: ${user.joined_date || user.joinedDate || 'June 1, 2026'}</p>
        </div>
      </div>

      <!-- Stats Grid -->
      <div class="profile-stats-grid" id="profile-stats-mount">
        <div class="stat-item-card">
          <h4 class="stat-spinner"><div class="spinner-ring" style="width: 20px; height: 20px; border-radius: 50%; border: 2px solid rgba(255, 255, 255, 0.05); border-top-color: #ff8da1; animation: spin 1s linear infinite; display: inline-block;"></div></h4>
          <p>Journal Entries</p>
        </div>
        <div class="stat-item-card">
          <h4>${user.streak || 1}d</h4>
          <p>Journal Streak</p>
        </div>
        <div class="stat-item-card">
          <h4 class="stat-spinner"><div class="spinner-ring" style="width: 20px; height: 20px; border-radius: 50%; border: 2px solid rgba(255, 255, 255, 0.05); border-top-color: #ff8da1; animation: spin 1s linear infinite; display: inline-block;"></div></h4>
          <p>Audio Recorded</p>
        </div>
        <div class="stat-item-card">
          <h4 class="stat-spinner"><div class="spinner-ring" style="width: 20px; height: 20px; border-radius: 50%; border: 2px solid rgba(255, 255, 255, 0.05); border-top-color: #ff8da1; animation: spin 1s linear infinite; display: inline-block;"></div></h4>
          <p>Avg Calmness</p>
        </div>
      </div>

      <!-- Favorites Section -->
      <div style="margin-top: 2rem;">
        <h3 style="font-family: var(--font-serif); font-size: 1.75rem; margin-bottom: 1.5rem; color: var(--color-orange); border-bottom: 1px solid var(--border-glow); padding-bottom: 0.5rem;">
          Favorite Memories
        </h3>
        
        <div class="timeline-grid" id="favorites-grid-mount">
          <div style="grid-column: span 3; text-align: center; padding: 2rem 0;">
            <div class="spinner-ring" style="width: 30px; height: 30px; border-radius: 50%; border: 3px solid rgba(255, 255, 255, 0.05); border-top-color: #ff8da1; animation: spin 1s linear infinite; display: inline-block;"></div>
          </div>
        </div>
      </div>
    `;

    return this.container;
  }

  async onMount() {
    const user = auth.getCurrentUser();
    if (!user) return;

    try {
      const memories = await intelApi.getTimeline();
      const favMemories = memories.filter(m => m.isFavorite);

      // Calculate dynamic stats
      const totalRecordedSecs = memories.reduce((acc, curr) => acc + (curr.duration || 0), 0);
      const avgStability = memories.length > 0 
        ? Math.round(memories.reduce((acc, curr) => acc + (curr.stability || 84), 0) / memories.length)
        : 84;

      // Populate stats grid
      const statsGrid = this.container.querySelector('#profile-stats-mount');
      if (statsGrid) {
        statsGrid.innerHTML = `
          <div class="stat-item-card">
            <h4>${memories.length}</h4>
            <p>Journal Entries</p>
          </div>
          <div class="stat-item-card">
            <h4>${user.streak || 1}d</h4>
            <p>Journal Streak</p>
          </div>
          <div class="stat-item-card">
            <h4>${totalRecordedSecs}s</h4>
            <p>Audio Recorded</p>
          </div>
          <div class="stat-item-card">
            <h4>${avgStability}%</h4>
            <p>Avg Calmness</p>
          </div>
        `;
      }

      // Populate favorites
      const favGrid = this.container.querySelector('#favorites-grid-mount');
      if (favGrid) {
        favGrid.innerHTML = '';
        if (favMemories.length === 0) {
          favGrid.innerHTML = `
            <div class="empty-timeline-msg" style="grid-column: span 3; width: 100%; text-align: center; padding: 3rem 1rem;">
              No favorite memories bookmarked. Click the star icon inside a journal entry to bookmark it!
            </div>
          `;
          return;
        }

        const cardFactory = new MemoryCard();
        favMemories.forEach(fav => {
          const cardEl = cardFactory.render(fav);
          favGrid.appendChild(cardEl);
        });
      }
    } catch (err) {
      console.error("Failed to load profile details:", err);
      const favGrid = this.container.querySelector('#favorites-grid-mount');
      if (favGrid) {
        favGrid.innerHTML = `
          <div class="empty-timeline-msg" style="grid-column: span 3; color: #ff5572; border-color: rgba(255, 85, 114, 0.15);">
            Failed to load favorites.
          </div>
        `;
      }
    }
  }
}
