import { useState, useEffect } from 'react'
import './App.css'

// IMPORTANT NOTE: if site restarts, does blockedsites empty? 
// EDGE CASE: does the actual hosts file on my computer stay blocked while the app 'forgets' they are blocked?

function App() {
    const [blockedSites, setBlockedSites] = useState([])
    const [newSite, setNewSite] = useState('')

    useEffect(() => {
        fetchBlockedSites()
    }, [])

    const fetchBlockedSites = async () => {
        try {
            const response = await fetch('http://127.0.0.1:5000/api/blocking')

            if (response.ok) {
                const data = await response.json()
                setBlockedSites(data.blocked_sites)
            }

        } catch (error) {
            console.error('Error fetching blocked sites:', error)
        }
    }

    const handleBlock = async (e) => {
        e.preventDefault()
        if (!newSite) return

        try {
            const response = await fetch('http://127.0.0.1:5000/api/block', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sites: [newSite] })
            })

            if (response.ok) {
                setNewSite('')
                fetchBlockedSites()
            }

        } catch (error) {
            console.error('Error blocking site:', error)
        }
    }

    const handleUnblock = async (site) => {
        try {
            const response = await fetch('http://127.0.0.1:5000/api/unblock', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sites: [site] })
            })
            if (response.ok) {
                fetchBlockedSites()
            }
        } catch (error) {
            console.error('Error unblocking site:', error)
        }
    }

    return (
        <div className="container">
            <header className="header">
                <h1 className="title">XamGuard</h1>
                <p className="subtitle">Master your focus. Eliminate distractions.</p>
            </header>

            <main className="main-content">
                <div className="card form-card">
                    <h2>Block a New Site</h2>
                    <form onSubmit={handleBlock} className="block-form">
                        <input
                            type="text"
                            placeholder="e.g. facebook.com"
                            value={newSite}
                            onChange={(e) => setNewSite(e.target.value)}
                            className="input-field"
                        />
                        <button type="submit" className="action-btn">Block Site</button>
                    </form>
                </div>

                <div className="card list-card">
                    <h2>Currently Blocked</h2>
                    {blockedSites.length === 0 ? (
                        <p className="empty-state">No sites are currently blocked. You are free to roam (carefully).</p>
                    ) : (
                        <ul className="site-list">
                            {blockedSites.map((site, index) => (
                                <li key={index} className="site-item">
                                    <span className="site-name">{site}</span>
                                    <button onClick={() => handleUnblock(site)} className="unblock-btn">Unblock</button>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            </main>
        </div>
    )
}

export default App
