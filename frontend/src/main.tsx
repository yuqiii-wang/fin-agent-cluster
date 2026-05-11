import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import 'antd/dist/reset.css';

// CSS for streaming cursor blink
const style = document.createElement('style');
style.textContent = '@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }';
document.head.appendChild(style);

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
