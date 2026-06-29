// Keep navigator.webdriver false inside iframes (sync reads via contentWindow).

() => {
  utils.preloadCache()

  const proxyNavigator = (nav) => {
    if (!nav) {
      return nav
    }
    return new Proxy(nav, {
      get(target, key) {
        if (key === 'webdriver') {
          return false
        }
        const value = Reflect.get(target, key)
        return typeof value === 'function' ? value.bind(target) : value
      }
    })
  }

  const proxyContentWindow = (win) => {
    if (!win) {
      return win
    }
    return new Proxy(win, {
      get(target, key) {
        if (key === 'navigator') {
          return proxyNavigator(Reflect.get(target, 'navigator'))
        }
        const value = Reflect.get(target, key)
        return typeof value === 'function' ? value.bind(target) : value
      }
    })
  }

  const patchNavigator = (nav) => {
    if (!nav) {
      return
    }
    const proto = Object.getPrototypeOf(nav)
    const desc = Object.getOwnPropertyDescriptor(proto, 'webdriver')
    if (desc && typeof desc.get === 'function' && nav.webdriver === false) {
      return
    }
    utils.replaceProperty(proto, 'webdriver', {
      get: () => false,
      set: () => undefined,
      configurable: true,
      enumerable: true,
    })
  }

  const patchWindow = (win) => {
    if (!win) {
      return
    }
    try {
      patchNavigator(win.navigator)
    } catch (_) {}
  }

  const iframeProto = HTMLIFrameElement.prototype
  const contentWindowDesc = Object.getOwnPropertyDescriptor(iframeProto, 'contentWindow')
  if (contentWindowDesc && typeof contentWindowDesc.get === 'function') {
    const nativeGet = contentWindowDesc.get
    utils.replaceProperty(iframeProto, 'contentWindow', {
      get() {
        return proxyContentWindow(nativeGet.call(this))
      },
      configurable: true,
      enumerable: true,
    })
  }

  patchWindow(globalThis)

  const patchIframe = (iframe) => {
    if (!iframe) {
      return
    }
    try {
      patchWindow(iframe.contentWindow)
    } catch (_) {}
  }

  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node instanceof HTMLIFrameElement) {
          patchIframe(node)
        } else if (node.querySelectorAll) {
          for (const iframe of node.querySelectorAll('iframe')) {
            patchIframe(iframe)
          }
        }
      }
    }
  })

  observer.observe(document.documentElement, { childList: true, subtree: true })
  for (const iframe of document.querySelectorAll('iframe')) {
    patchIframe(iframe)
  }
}