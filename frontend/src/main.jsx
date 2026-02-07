import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

// est the hunter for root
const rootElement = document.getElementById('root');

// est the rock
const root = createRoot(rootElement);

// est renderer
root.render(
    <StrictMode>
        <App />
    </StrictMode>,
)
