import '@/assets/confirmation.css'

interface Confirmation {
  title: string
  message: string
  confirmLabel?: string
}

let serial = 0

/** Keep confirmation at the action owner and return false for every dismissal. */
export function confirmAction(options: Confirmation): Promise<boolean> {
  if (typeof document === 'undefined') return Promise.resolve(false)
  const dialog = document.createElement('dialog')
  dialog.className = 'confirmation-dialog'
  const title = document.createElement('h2')
  title.id = `confirmation-title-${++serial}`
  title.textContent = options.title
  dialog.setAttribute('aria-labelledby', title.id)
  const message = document.createElement('p')
  message.textContent = options.message
  const form = document.createElement('form')
  form.method = 'dialog'
  const cancel = document.createElement('button')
  cancel.type = 'submit'
  cancel.value = 'cancel'
  cancel.textContent = 'Cancel'
  cancel.autofocus = true
  const approve = document.createElement('button')
  approve.type = 'submit'
  approve.value = 'confirm'
  approve.className = 'confirmation-approve'
  approve.textContent = options.confirmLabel || 'Confirm'
  form.append(cancel, approve)
  dialog.append(title, message, form)
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return
    const box = dialog.getBoundingClientRect()
    if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close('cancel')
  })
  return new Promise(resolve => {
    dialog.addEventListener('close', () => {
      const confirmed = dialog.returnValue === 'confirm'
      dialog.remove()
      resolve(confirmed)
    }, { once: true })
    document.body.append(dialog)
    dialog.showModal()
  })
}
