// Mitigate Runtime.Enable CDP leak — never pass Error objects to native console APIs.

() => {
  const stringifyError = (err) => {
    const saved = Error.prepareStackTrace
    Error.prepareStackTrace = undefined
    try {
      const message = err.message || 'Error'
      const stack = err.stack || ''
      if (!stack) {
        return message
      }
      return stack.includes(message) ? stack : `${message}\n${stack}`
    } finally {
      if (saved !== undefined) {
        Error.prepareStackTrace = saved
      }
    }
  }

  const mapArgs = (args) =>
    args.map((arg) => (arg instanceof Error ? stringifyError(arg) : arg))

  const install = () => {
    if (!globalThis.console) {
      return
    }
    for (const name of [
      'log',
      'debug',
      'info',
      'warn',
      'error',
      'trace',
      'dir',
      'dirxml',
      'assert'
    ]) {
      const current = console[name]
      if (typeof current !== 'function' || current.__untraceCdpWrapped) {
        continue
      }
      const bound = current.bind(console)
      const wrapped = function (...args) {
        return bound(...mapArgs(args))
      }
      wrapped.__untraceCdpWrapped = true
      try {
        console[name] = wrapped
      } catch (_) {
        try {
          Object.defineProperty(console, name, {
            value: wrapped,
            writable: true,
            configurable: true
          })
        } catch (_) {}
      }
    }
  }

  install()
  queueMicrotask(install)
  setTimeout(install, 0)
  setInterval(install, 4)

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', install, { once: true })
  }
}