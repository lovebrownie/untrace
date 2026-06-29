// Strip HeadlessChrome from navigator UA strings and client hints.

() => {
  utils.preloadCache()
  const proto = Object.getPrototypeOf(navigator)
  const stripHeadless = (value) =>
    typeof value === 'string' ? value.replace(/HeadlessChrome/g, 'Chrome') : value

  const patchGetter = (prop) => {
    const current = Object.getOwnPropertyDescriptor(proto, prop)
    if (!current || typeof current.get !== 'function') {
      return
    }
    const nativeGet = current.get
    utils.replaceProperty(proto, prop, {
      get: () => stripHeadless(nativeGet.call(navigator)),
      set: () => undefined,
      configurable: true,
      enumerable: true,
    })
  }

  patchGetter('userAgent')
  patchGetter('appVersion')

  const data = navigator.userAgentData
  if (data) {
    const dataProto = Object.getPrototypeOf(data)
    const brandsDesc = Object.getOwnPropertyDescriptor(dataProto, 'brands')
    if (brandsDesc && typeof brandsDesc.get === 'function') {
      const nativeBrands = brandsDesc.get
      utils.replaceProperty(dataProto, 'brands', {
        get: () =>
          nativeBrands.call(data).map((entry) => ({
            ...entry,
            brand: stripHeadless(entry.brand),
          })),
        configurable: true,
        enumerable: true,
      })
    }
  }
}