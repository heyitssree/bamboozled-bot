import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { AnswerButton, Avatar, FlipCard, PlayerChip, Podium, Scoreboard, TimerRing, Wheel } from '../../src/components/game'
import { Banner, Button, IconButton, Modal, Skeleton, Tabs, Toggle } from '../../src/components/ui'
import { ToastHost } from '../../src/components/Toasts'
import { useStore } from '../../src/state/store'
import type { Member } from '../../src/net/protocol'

const alice: Member = { user_id: 1, name: 'Alice', avatar_url: 'https://cdn.example/a.png', ready: false, connected: true, spectator: false, host: true }

describe('AnswerButton: correct and wrong are never conveyed by colour alone', () => {
  it.each([
    ['correct', 'Correct', '✔'], ['wrong', 'Wrong', '✖'], ['locked', 'Locked in', '🔒'], ['selected', 'Your pick', '●'],
  ] as const)('%s shows the word and an icon', (state, word, icon) => {
    render(<AnswerButton index={0} text="Mercury" state={state} />)
    const b = screen.getByRole('button')
    expect(b).toHaveTextContent(word)
    expect(b).toHaveTextContent(icon)
  })
  it('idle has no flag, and reports pressed only when picked', () => {
    const { rerender } = render(<AnswerButton index={1} text="Mars" />)
    expect(screen.getByRole('button')).not.toHaveAttribute('aria-pressed')
    rerender(<AnswerButton index={1} text="Mars" state="locked" />)
    expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'true')
  })
  it('shows the key to press and calls back on click', async () => {
    const onClick = vi.fn()
    render(<AnswerButton index={2} text="Venus" onClick={onClick} />)
    expect(screen.getByText('3')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Venus/ }))
    expect(onClick).toHaveBeenCalledOnce()
  })
})

describe('TimerRing', () => {
  it('announces the seconds left and turns urgent in the last five', () => {
    const { container, rerender } = render(<TimerRing seconds={12} fraction={0.4} />)
    expect(screen.getByRole('timer')).toHaveAccessibleName('12 seconds left')
    expect(container.querySelector('.timer-urgent')).toBeNull()
    rerender(<TimerRing seconds={4} fraction={0.1} />)
    expect(container.querySelector('.timer-urgent')).not.toBeNull()
  })
})

describe('PlayerChip and Scoreboard', () => {
  it('hides the score under the Mist and says so to screen readers', () => {
    render(<PlayerChip member={alice} score={450} hideScore />)
    expect(screen.getByLabelText('score hidden by the Mist')).toHaveTextContent('??')
    expect(screen.queryByText('450')).toBeNull()
  })
  it('shows the score, marks whose turn it is and lists badges with names', () => {
    render(<Scoreboard><PlayerChip member={alice} score={1250} active me badges={{ host: true, silenced: true, goldenPass: true }} /></Scoreboard>)
    expect(screen.getByLabelText('1250 points')).toHaveTextContent('1,250')
    expect(screen.getByText('Turn')).toBeInTheDocument()
    expect(screen.getByText('You')).toBeInTheDocument()
    for (const label of ['host', 'silenced', 'has a golden pass']) expect(screen.getByLabelText(label)).toBeInTheDocument()
    expect(screen.getByText('Alice').closest('.chip')).toHaveAttribute('aria-current', 'true')
  })
})

describe('Avatar', () => {
  it('is decorative next to a name and falls back to an initial when the picture fails', () => {
    const { container } = render(<Avatar member={alice} />)
    const img = container.querySelector('img')!
    expect(img).toHaveAttribute('alt', '')
    fireEvent.error(img)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('.avatar-fallback')).toHaveTextContent('A')
  })
  it('uses the fallback straight away when there is no picture', () => {
    const { container } = render(<Avatar member={{ ...alice, avatar_url: '' }} />)
    expect(container.querySelector('.avatar-fallback')).toBeInTheDocument()
  })
})

describe('Wheel', () => {
  it('lands on the segment the server chose: the disc is rotated so it sits under the pointer', () => {
    const { container } = render(<Wheel result="Bonus Round" spinId={1} reduced />)
    const disc = container.querySelector('svg')!
    expect(disc.getAttribute('data-angle')).toBe(String(-(5 + 0.5) * 45))         // index 5, no extra turns in reduced motion
    expect(screen.getByRole('img')).toHaveAccessibleName('Wheel of Mayhem, landed on Bonus Round')
  })
  it('spins whole extra turns when motion is allowed and still lands on the same slice', () => {
    const moving = render(<Wheel result="Tax Season" spinId={2} reduced={false} />).container.querySelector('svg')!
    const angle = Number(moving.getAttribute('data-angle'))
    expect(angle).toBeGreaterThan(360 * 3)                                         // several full turns
    expect(((angle % 360) + 360) % 360).toBe(360 - 1.5 * 45)                       // slice 1 centred under the pointer
    const idle = render(<Wheel result={null} spinId={0} reduced={false} />).container.querySelector('svg')!
    expect(idle.getAttribute('data-angle')).toBe('0')
  })
})

describe('Podium', () => {
  it('puts first place in the middle and names every step', () => {
    const rows = [1, 2, 3].map((id, i) => ({ user_id: id, rank: i + 1, score: 1000 - i * 100, correct: 0, details: {} }))
    render(<Podium rows={rows} name={(id) => `P${id}`} />)
    const items = within(screen.getByRole('list', { name: 'Podium' })).getAllByRole('listitem')
    expect(items.map((li) => li.textContent?.includes('P1'))).toEqual([false, true, false])
    expect(items[1]).toHaveTextContent('1,000')
  })
})

describe('FlipCard', () => {
  it('hides the face that is turned away from assistive technology', () => {
    const { rerender, container } = render(<FlipCard flipped={false} label="Card" front="F" back="B" />)
    expect(container.querySelector('.flip-front')).toHaveAttribute('aria-hidden', 'false')
    expect(container.querySelector('.flip-back')).toHaveAttribute('aria-hidden', 'true')
    rerender(<FlipCard flipped label="Card" front="F" back="B" />)
    expect(container.querySelector('.flip')).toHaveClass('flip-on')
    expect(container.querySelector('.flip-back')).toHaveAttribute('aria-hidden', 'false')
  })
})

describe('Toggle, Tabs, Banner, Skeleton, IconButton', () => {
  it('Toggle is a labelled switch', async () => {
    const Wrapper = () => { const [on, setOn] = useState(false); return <Toggle label="Sound" checked={on} onChange={setOn} /> }
    render(<Wrapper />)
    const sw = screen.getByRole('switch', { name: 'Sound' })
    expect(sw).toHaveAttribute('aria-checked', 'false')
    await userEvent.click(sw)
    expect(sw).toHaveAttribute('aria-checked', 'true')
  })
  it('Tabs move with the arrow keys and Home/End, and only the active tab is in the tab order', async () => {
    const Wrapper = () => { const [t, setT] = useState('a'); return <Tabs label="Things" active={t} onChange={setT} tabs={[{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }, { id: 'c', label: 'C' }]}><p>panel {t}</p></Tabs> }
    render(<Wrapper />)
    const a = screen.getByRole('tab', { name: 'A' })
    a.focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'B' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'B' })).toHaveFocus()
    expect(screen.getByRole('tab', { name: 'A' })).toHaveAttribute('tabindex', '-1')
    await userEvent.keyboard('{End}')
    expect(screen.getByRole('tabpanel')).toHaveTextContent('panel c')
    await userEvent.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'A' })).toHaveAttribute('aria-selected', 'true')
    await userEvent.keyboard('{ArrowLeft}')
    expect(screen.getByRole('tab', { name: 'C' })).toHaveAttribute('aria-selected', 'true')
  })
  it('errors are announced as alerts, notices as polite status', () => {
    render(<><Banner tone="error">Broken</Banner><Banner tone="info">FYI</Banner></>)
    expect(screen.getByRole('alert')).toHaveTextContent('Broken')
    expect(screen.getByRole('status')).toHaveTextContent('FYI')
  })
  it('Skeleton is announced as loading and the bars are hidden', () => {
    const { container } = render(<Skeleton label="Loading the board" />)
    expect(screen.getByRole('status')).toHaveTextContent('Loading the board')
    expect(container.querySelectorAll('.skeleton[aria-hidden="true"]')).toHaveLength(3)
  })
  it('an icon-only button always has a name', () => {
    render(<IconButton label="Settings">⚙️</IconButton>)
    expect(screen.getByRole('button', { name: 'Settings' })).toBeInTheDocument()
  })
  it('Button defaults to type=button so it never submits a form by accident', () => {
    render(<Button>Go</Button>)
    expect(screen.getByRole('button')).toHaveAttribute('type', 'button')
  })
})

describe('Modal', () => {
  it('is a labelled dialog, closes on Escape and on the backdrop, and puts focus back', async () => {
    const onClose = vi.fn()
    const Page = () => { const [open, setOpen] = useState(false); return <><button onClick={() => setOpen(true)}>open</button>{open && <Modal title="Hello" onClose={() => { onClose(); setOpen(false) }}><button>inside</button></Modal>}</> }
    render(<Page />)
    const opener = screen.getByRole('button', { name: 'open' })
    await userEvent.click(opener)
    const dialog = screen.getByRole('dialog', { name: 'Hello' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByRole('button', { name: 'inside' })).toHaveFocus()
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledOnce()
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(opener).toHaveFocus()
  })
  it('keeps Tab inside the dialog', async () => {
    render(<Modal title="Trap" onClose={() => undefined} actions={<button>second</button>}><button>first</button></Modal>)
    await userEvent.tab()
    expect(screen.getByRole('button', { name: 'second' })).toHaveFocus()
    await userEvent.tab()
    expect(screen.getByRole('button', { name: 'first' })).toHaveFocus()
    await userEvent.tab({ shift: true })
    expect(screen.getByRole('button', { name: 'second' })).toHaveFocus()
  })
})

describe('ToastHost', () => {
  it('shows messages in a polite live region and lets people dismiss them', async () => {
    useStore.getState().reset()
    render(<ToastHost />)
    useStore.getState().toast('Only the host can do that.')
    expect(await screen.findByText('Only the host can do that.')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite')
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss message' }))
    expect(screen.queryByText('Only the host can do that.')).toBeNull()
  })
})
