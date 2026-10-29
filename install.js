// Home-screen installation is provided by Safari's Share menu. Keep its help
// inside the existing dialog, and make the installed game available offline.
if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.protocol === 'http:')) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('./sw.js', {updateViaCache: 'none'}).catch(() => {
      // Private browsing or storage restrictions must not prevent normal play.
    });
  });
}
