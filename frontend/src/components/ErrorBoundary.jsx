import { Component } from 'react';

export default class ErrorBoundary extends Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) return <main className="card" role="alert">
      <h2>This view could not be displayed</h2>
      <button className="btn-primary" onClick={() => { window.location.hash = 'dashboard'; window.location.reload(); }}>Return to dashboard</button>
    </main>;
    return this.props.children;
  }
}