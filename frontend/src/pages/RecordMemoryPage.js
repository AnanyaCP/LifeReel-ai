/**
 * LifeReel AI - RecordMemoryPage View
 */
import { AudioRecorder } from '../components/AudioRecorder.js';
import { UploadBox } from '../components/UploadBox.js';

export class RecordMemoryPage {
  constructor() {
    this.recorder = null;
    this.uploader = null;
  }

  render() {
    const container = document.createElement('div');
    container.className = 'page-view recorder-container';

    container.innerHTML = `
      <div class="recorder-header-wrap">
        <h2 class="recorder-title">Record Today's Memory</h2>
        <p class="recorder-subtitle">Speak freely or upload an audio file. We will write it down and save it to your diary.</p>
      </div>

      <!-- Recorder Widget Hook -->
      <div id="recorder-widget-mount" style="width: 100%;"></div>

      <!-- Divider line -->
      <div style="width: 100%; max-width: 600px; height: 1px; background: var(--border-glow); margin: 2.5rem 0;"></div>

      <!-- Waveform Uploader Widget Hook -->
      <div id="uploader-widget-mount" style="width: 100%;"></div>

      <!-- Manual text overlay -->
      <div class="manual-input-box">
        <h4>Write Today's Memory</h4>
        <textarea class="manual-textarea" id="text-memory-input" placeholder="Write your thoughts here... What happened today? How did you feel?"></textarea>
        <button class="btn-submit-memory" id="btn-submit-text">
          <span>Save Memory</span>
          <i class="bi bi-send-fill"></i>
        </button>
      </div>
    `;

    // Mount AudioRecorder
    const handleRecordStop = (blob, duration) => {
      // Save recorded Blob to window state
      window.lifereel_recorded_blob = blob;
      sessionStorage.setItem('lifereel_draft', JSON.stringify({
        type: 'audio',
        duration: duration,
        rawInput: '' // API will generate transcription
      }));
      window.location.hash = '#processing';
    };
    this.recorder = new AudioRecorder(handleRecordStop);
    container.querySelector('#recorder-widget-mount').appendChild(this.recorder.render());

    // Mount UploadBox
    const handleUploadComplete = (file, duration) => {
      // Save uploaded file (Blob) to window state
      window.lifereel_recorded_blob = file;
      sessionStorage.setItem('lifereel_draft', JSON.stringify({
        type: 'upload',
        duration: duration,
        rawInput: `Transcribed audio file: ${file.name}`
      }));
      window.location.hash = '#processing';
    };
    this.uploader = new UploadBox(handleUploadComplete);
    container.querySelector('#uploader-widget-mount').appendChild(this.uploader.render());

    // Handle Manual Text Submit
    const textarea = container.querySelector('#text-memory-input');
    const submitBtn = container.querySelector('#btn-submit-text');

    submitBtn.addEventListener('click', () => {
      const content = textarea.value.trim();
      if (!content) {
        alert('Please write something down before saving!');
        return;
      }

      sessionStorage.setItem('lifereel_draft', JSON.stringify({
        type: 'text',
        duration: Math.max(10, Math.ceil(content.split(' ').length * 0.4)), // dynamic scale based on length
        rawInput: content
      }));
      window.location.hash = '#processing';
    });

    return container;
  }

  onMount() {}

  destroy() {
    if (this.recorder) {
      this.recorder.destroy();
    }
  }
}
