/**
 * LifeReel AI - Core API Layer
 * Connects the vanilla JS frontend with the FastAPI backend endpoints.
 */
import { db } from '../utils/db.js';

export class LifeReelAPI {
  constructor() {
    const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
    // Expose local backend securely to the Render frontend via ngrok
    this.baseUrl = 'https://lifereel-ai-zfiu.onrender.com';
  }

  /**
   * Helper to retrieve headers with Authorization token.
   */
  _getHeaders(additionalHeaders = {}) {
    const token = localStorage.getItem('lifereel_jwt_token');
    return {
      ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      ...additionalHeaders
    };
  }

  /**
   * Helper to normalize a backend entry to the frontend structure.
   */
  _normalizeEntry(item) {
    if (!item) return item;
    const id = item.id || item._id;
    const rawEmotion = item.emotion || item.dominant_emotion || item.mood || 'Calm';
    
    const emotionToMood = {
      'joy': 'Joyful',
      'calm': 'Calm',
      'melancholy': 'Nostalgic',
      'productive': 'Inspired',
      'anxious': 'Calm',
      'grateful': 'Grateful',
      'joyful': 'Joyful',
      'inspired': 'Inspired',
      'nostalgic': 'Nostalgic'
    };

    const emotionStabilityMap = {
      'Calm': 92,
      'Joyful': 88,
      'Inspired': 82,
      'Grateful': 80,
      'Nostalgic': 78
    };

    const mood = emotionToMood[rawEmotion.toLowerCase()] || 'Calm';
    const narrative = item.story || item.narrative || '';
    const image = item.image_url || item.image || '';
    const hasImage = !!image;
    const duration = item.duration || Math.max(10, Math.ceil((item.transcript || '').split(' ').length * 0.4));
    const stability = item.stability || emotionStabilityMap[mood] || 84;
    
    // Check local favorite store
    const isFavorite = db.getAll().some(m => m.id === id && m.isFavorite);
    
    const date = item.created_at
      ? new Date(item.created_at).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
      : (item.date_string || item.date || '');

    return {
      ...item,
      id,
      mood,
      narrative,
      image,
      hasImage,
      duration,
      stability,
      isFavorite,
      date
    };
  }

  /**
   * Uploads recorded audio and runs the full AI processing pipeline.
   * @param {Blob} audioBlob - The recorded voice entry.
   * @returns {Promise<Object>} The created MemoryResponse payload.
   */
  async createMemory(audioBlob) {
    const formData = new FormData();
    // Append the blob as 'audio' with a filename of 'voice_entry.wav'
    formData.append('audio', audioBlob, 'voice_entry.wav');

    const response = await fetch(`${this.baseUrl}/api/memory/create`, {
      method: 'POST',
      headers: this._getHeaders(),
      body: formData,
    });

    if (!response.ok) {
      const errorDetail = await response.text();
      throw new Error(`API Error: ${response.status} - ${errorDetail || response.statusText}`);
    }

    const data = await response.json();
    return this._normalizeEntry(data);
  }

  /**
   * Generates a text-only journal entry and processes it.
   * @param {string} rawText - The typed entry text.
   * @returns {Promise<Object>} The created DiaryResponse payload.
   */
  async generateEntry(rawText) {
    const response = await fetch(`${this.baseUrl}/api/entries/generate`, {
      method: 'POST',
      headers: this._getHeaders({
          'Content-Type': 'application/json'
      }),
      body: JSON.stringify({ raw_text: rawText }),
    });

    if (!response.ok) {
      const errorDetail = await response.text();
      throw new Error(`API Error: ${response.status} - ${errorDetail || response.statusText}`);
    }

    const data = await response.json();
    return this._normalizeEntry(data);
  }

  /**
   * Fetches all persisted memories from the backend, sorted newest first.
   * @returns {Promise<Array>} List of timeline memories.
   */
  async getTimeline() {
    const response = await fetch(`${this.baseUrl}/api/entries/timeline`, {
      headers: this._getHeaders()
    });
    if (!response.ok) {
      throw new Error(`Failed to fetch timeline: ${response.status} ${response.statusText}`);
    }
    const data = await response.json();
    const timeline = data.timeline || [];
    return timeline.map(item => this._normalizeEntry(item));
  }

  /**
   * Fetches details of a single memory or diary entry.
   * @param {string} id - Stringified MongoDB ObjectID of the entry.
   * @returns {Promise<Object>} DiaryResponse or MemoryResponse payload.
   */
  async getEntry(id) {
    const response = await fetch(`${this.baseUrl}/api/entries/${id}`, {
      headers: this._getHeaders()
    });
    if (!response.ok) {
      throw new Error(`Failed to fetch entry: ${response.status} ${response.statusText}`);
    }
    const data = await response.json();
    return this._normalizeEntry(data);
  }

  /**
   * Deletes a single memory or diary entry from the database.
   * @param {string} id - Stringified MongoDB ObjectID.
   * @returns {Promise<Object>} Status response.
   */
  async deleteEntry(id) {
    const response = await fetch(`${this.baseUrl}/api/entries/${id}`, {
      method: 'DELETE',
      headers: this._getHeaders()
    });
    if (!response.ok) {
      throw new Error(`Failed to delete entry: ${response.status} ${response.statusText}`);
    }
    return await response.json();
  }
}

// Export a singleton instance under the legacy name for seamless compatibility
export const intelApi = new LifeReelAPI();
export const moodMapping = {
  Calm: { tag: '🌸 Soothing Wave', color: 'var(--mood-calm)' },
  Nostalgic: { tag: '🧸 Warm Hug', color: 'var(--mood-nostalgic)' },
  Inspired: { tag: '✨ Sparkle Dust', color: 'var(--mood-inspired)' },
  Grateful: { tag: '💖 Sweet Heart', color: 'var(--mood-grateful)' },
  Joyful: { tag: '☀️ Happy Sunshine', color: 'var(--mood-joyful)' }
};
