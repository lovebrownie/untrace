// Hide navigator.headless when Chrome exposes it (headless builds).

() => {
  utils.preloadCache()
  const proto = Object.getPrototypeOf(navigator)
  if (!('headless' in navigator)) {
    return
  }
  utils.replaceProperty(proto, 'headless', {
    get: () => false,
    set: () => undefined,
    configurable: true,
    enumerable: true,
  })
}