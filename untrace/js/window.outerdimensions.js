// https://github.com/berstend/puppeteer-extra/blob/c44c8bb0224c6bba2554017bfb9d7a1d0119f92f/packages/puppeteer-extra-plugin-stealth/evasions/window.outerdimensions/index.js

() => {
  utils.preloadCache()

  const windowFrame = 85
  if (!window.outerWidth || window.outerWidth === window.innerWidth) {
    utils.replaceProperty(window, 'outerWidth', {
      get: () => window.innerWidth,
      configurable: true,
      enumerable: true,
    })
    utils.replaceProperty(window, 'outerHeight', {
      get: () => window.innerHeight + windowFrame,
      configurable: true,
      enumerable: true,
    })
  }

  const screenProto = Object.getPrototypeOf(screen)
  const patchScreen = (prop, value) => {
    utils.replaceProperty(screenProto, prop, {
      get: () => value,
      configurable: true,
      enumerable: true,
    })
  }

  if (screen.width <= 800 || screen.height <= 600) {
    patchScreen('width', 1920)
    patchScreen('height', 1080)
    patchScreen('availWidth', 1920)
    patchScreen('availHeight', 1040)
    patchScreen('colorDepth', 24)
    patchScreen('pixelDepth', 24)
  }
}