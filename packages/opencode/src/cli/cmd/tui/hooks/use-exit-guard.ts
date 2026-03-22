import { onCleanup } from "solid-js"
import { useExit } from "../context/exit"
import { useToast } from "../ui/toast"

const GUARD_TIMEOUT_MS = 2500

export function useExitGuard() {
  const exit = useExit()
  const toast = useToast()
  let timer: ReturnType<typeof setTimeout> | undefined
  let armed = false

  onCleanup(() => {
    if (timer) clearTimeout(timer)
  })

  return {
    /** Guarded exit: first call shows toast, second call within timeout exits */
    tryExit: async () => {
      if (armed) {
        if (timer) clearTimeout(timer)
        await exit()
        return
      }
      armed = true
      toast.show({ message: "Press again to exit", variant: "warning", duration: GUARD_TIMEOUT_MS })
      timer = setTimeout(() => {
        armed = false
        timer = undefined
      }, GUARD_TIMEOUT_MS)
    },
    /** Immediate exit, no guard (for /exit, /quit, :q) */
    forceExit: () => exit(),
  }
}
