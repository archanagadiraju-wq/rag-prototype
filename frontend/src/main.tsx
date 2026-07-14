import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// Files dropped anywhere outside an explicit drop-target would otherwise trigger
// the browser's default "open this file" behavior — which navigates the tab away
// from the app and looks like a refresh. Swallow drops at the window level; the
// react-dropzone target stops propagation before this fires on a real drop.
const swallow = (e: DragEvent) => { e.preventDefault() }
window.addEventListener('dragover', swallow)
window.addEventListener('drop', swallow)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
