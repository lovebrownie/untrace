// https://github.com/berstend/puppeteer-extra/blob/c44c8bb0224c6bba2554017bfb9d7a1d0119f92f/packages/puppeteer-extra-plugin-stealth/evasions/navigator.languages/index.js

(languages) => {
  const list = languages || ['en-US', 'en']
  const proto = Object.getPrototypeOf(navigator)

  Object.defineProperty(proto, 'languages', {
    get: () => list,
    configurable: true,
    enumerable: true
  })

  Object.defineProperty(proto, 'language', {
    get: () => list[0],
    configurable: true,
    enumerable: true
  })
}