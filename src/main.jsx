import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryProvider } from './lib/QueryProvider'
import UpdateNotifier from './components/Layout/UpdateNotifier'
import { clearStaleServiceWorkers } from './lib/swCleanup'
import App from './App.jsx'
import './index.css'

clearStaleServiceWorkers()

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <QueryProvider>
      {/* Outside <App/>: the login and loading screens render without the
          Router, and a stale tab parked there still needs the update prompt. */}
      <UpdateNotifier />
      <App />
    </QueryProvider>
  </React.StrictMode>,
)