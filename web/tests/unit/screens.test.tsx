import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FIXTURES, fixtureById } from '../../src/app/fixtures'
import { Lobby } from '../../src/screens/Lobby'
import { Results } from '../../src/screens/Results'
import { Splash } from '../../src/screens/Splash'
import { useStore } from '../../src/state/store'
import BamboozledScreen from '../../src/screens/Bamboozled'
import FffScreen from '../../src/screens/Fff'
import SurvivalScreen from '../../src/screens/Survival'

const sent = vi.hoisted(() => [] as unknown[])
vi.mock('../../src/app/connection', () => ({
  send: (m: unknown) => { sent.push(m); return true }, retry: vi.fn(), authHeaders: () => ({}), startApp: vi.fn(),
}))
vi.mock('../../src/app/api', () => ({
  fetchMyStats: async () => ({ games: 3, wins: 1, best_score: 900, total_score: 2000, best_streak: 4 }),
  fetchBoard: async () => [], postPrivacy: async () => 'done',
}))

function show(id: string) {
  const f = fixtureById(id)!
  const st = useStore.getState()
  st.reset()
  if (f.room) st.applyState(f.room)
  if (f.lastQuestion) useStore.setState({ lastQuestion: f.lastQuestion })
  return f
}
const renderScreen = (id: string) => {
  const f = show(id)
  const room = f.room!
  const Screen = room.phase === 'lobby' ? Lobby : room.phase === 'results' ? Results
    : room.mode === 'bamboozled' ? BamboozledScreen : room.mode === 'fff' ? FffScreen : SurvivalScreen
  return render(<Screen room={room} />)
}

beforeEach(() => { sent.length = 0 })

describe('every gallery screen renders, with a main landmark', () => {
  for (const f of FIXTURES.filter((x) => x.room && !x.dialog && !x.interrupted && !x.roomClosed)) {
    it(f.id, () => {
      const { container } = renderScreen(f.id)
      expect(container.querySelector('main')).not.toBeNull()
    })
  }
})

describe('Splash covers every way in', () => {
  const cases: [string, RegExp][] = [
    ['splash-loading', /Signing in/], ['splash-joining', /Joining the game/], ['splash-not-in-discord', /Open Bamboozled from Discord/],
    ['splash-auth-failed', /Could not sign in/], ['splash-not-in-instance', /can’t join this game/], ['splash-opted-out', /You have opted out/],
    ['splash-unknown-instance', /session has ended/], ['splash-full', /full right now/], ['splash-maintenance', /Back in a moment/],
    ['splash-replaced', /another window/],
  ]
  it.each(cases)('%s', (id, title) => {
    const f = fixtureById(id)!
    show(id)
    const boot = f.boot === 'not_in_discord' ? { phase: 'error' as const, kind: 'not_in_discord' as const, message: '' }
      : f.boot === 'loading' ? { phase: 'loading' as const } : { phase: 'ready' as const }
    render(<Splash boot={boot} fatal={f.fatal ?? null} joining={f.state === 'joining'} />)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(title)
  })
  it('error screens that can be retried have a button, the final ones do not', () => {
    for (const [id, retry] of [['splash-auth-failed', true], ['splash-full', true], ['splash-maintenance', true], ['splash-replaced', true],
      ['splash-opted-out', false], ['splash-not-in-instance', false], ['splash-unknown-instance', false]] as const) {
      const f = fixtureById(id)!
      const { unmount } = render(<Splash boot={{ phase: 'ready' }} fatal={f.fatal ?? null} />)
      expect(screen.queryByRole('button') !== null, id).toBe(retry)
      unmount()
    }
  })
})

describe('Lobby', () => {
  it('the host picks the game, changes settings and can start; messages go to the server', async () => {
    renderScreen('lobby-host')
    await userEvent.click(screen.getByTestId('mode-fff'))
    await userEvent.selectOptions(screen.getByLabelText('Difficulty'), 'hard')
    await userEvent.click(screen.getByRole('button', { name: 'Start the game' }))
    expect(sent).toEqual([{ t: 'SET_MODE', d: { mode: 'fff' } }, { t: 'SET_CONFIG', d: { difficulty: 'hard' } }, { t: 'START' }])
  })
  it('a player cannot change anything and sees who is choosing', () => {
    renderScreen('lobby-player')
    expect(screen.getByTestId('mode-fff')).toBeDisabled()
    expect(screen.getByLabelText('Rounds')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Start the game' })).toBeNull()
    expect(screen.getByText(/Alice/, { selector: 'strong' })).toBeInTheDocument()
    expect(screen.getByText('Waiting for the host to start.')).toBeInTheDocument()
  })
  it('says how many more players are needed, and a spectator cannot ready up', () => {
    const { unmount } = renderScreen('lobby-below-minimum')
    expect(screen.getByText('Waiting for 1 more player.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start the game' })).toBeDisabled()
    unmount()
    renderScreen('lobby-spectator')
    expect(screen.getByText(/you are watching/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Ready/ })).toBeNull()
  })
  it('ready toggles', async () => {
    renderScreen('lobby-player')
    await userEvent.click(screen.getByRole('button', { name: 'Ready' }))
    expect(sent).toEqual([{ t: 'READY', d: { ready: true } }])
  })
})

describe('Bamboozled', () => {
  it('my turn: answers are live, picking one sends it, and 1 to 4 work as keys', async () => {
    renderScreen('bz-my-question')
    expect(screen.getByRole('region', { name: 'Question' })).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('answer-2'))
    expect(sent).toEqual([{ t: 'ANSWER', d: { index: 2 } }])
    expect(screen.getByText('Answer sent…')).toBeInTheDocument()
  })
  it('keys pick an answer', async () => {
    renderScreen('bz-my-question')
    await userEvent.keyboard('3')
    expect(sent).toEqual([{ t: 'ANSWER', d: { index: 2 } }])
  })
  it("waiting for someone else's answer: all answers are disabled", () => {
    renderScreen('bz-waiting-question')
    for (let i = 0; i < 4; i++) expect(screen.getByTestId(`answer-${i}`)).toBeDisabled()
    expect(screen.getByText('Alice is answering…')).toBeInTheDocument()
  })
  it('the reveal marks the right answer and the wrong pick with words, not just colour', () => {
    renderScreen('bz-reveal-wrong')
    expect(screen.getByTestId('answer-2')).toHaveTextContent('Correct')
    expect(screen.getByTestId('answer-0')).toHaveTextContent('Wrong')
    expect(screen.getByText(/You missed it/)).toBeInTheDocument()
  })
  it('the Mist hides every score and says why', () => {
    renderScreen('bz-mist')
    expect(screen.getAllByLabelText('score hidden by the Mist').length).toBe(3)
    expect(screen.getByText(/Mystic Mist hides every score/)).toBeInTheDocument()
  })
  it('each decision has its control, only for the player it belongs to', async () => {
    const { unmount } = renderScreen('bz-pick-swap')
    await userEvent.click(screen.getByRole('button', { name: /Bob/ }))
    await userEvent.click(screen.getByRole('button', { name: /No thanks/ }))
    expect(sent).toEqual([{ t: 'PICK_TARGET', d: { user_id: 2 } }, { t: 'PICK_TARGET', d: { user_id: null } }])
    unmount()
    sent.length = 0
    renderScreen('bz-pick-law')
    await userEvent.click(screen.getByRole('button', { name: /Karma Tax/ }))
    expect(sent).toEqual([{ t: 'PICK_RULE', d: { rule_id: 5 } }])
  })
  it('the monkey has two big buttons for the active player and a message for the others', async () => {
    const { unmount } = renderScreen('bz-monkey')
    await userEvent.click(screen.getByRole('button', { name: /Tail/ }))
    expect(sent).toEqual([{ t: 'MONKEY', d: { choice: 'tail' } }])
    unmount()
    renderScreen('bz-monkey-waiting')
    expect(screen.queryByRole('button', { name: /Belly/ })).toBeNull()
    expect(screen.getByText('Alice faces the monkey…')).toBeInTheDocument()
  })
  it('a spectator sees the question but has nothing to press', () => {
    renderScreen('bz-spectator')
    expect(screen.getByText('You are watching this game.')).toBeInTheDocument()
    for (let i = 0; i < 4; i++) expect(screen.getByTestId(`answer-${i}`)).toBeDisabled()
  })
  it('the wheel shows its result and a spin button for the active player', async () => {
    renderScreen('bz-spin')
    await userEvent.click(screen.getByRole('button', { name: 'Spin the wheel!' }))
    expect(sent).toEqual([{ t: 'SPIN' }])
  })
})

describe('Fastest Fingers', () => {
  it('open question: answering locks it in', async () => {
    renderScreen('fff-open')
    await userEvent.click(screen.getByTestId('answer-1'))
    expect(sent).toEqual([{ t: 'ANSWER', d: { index: 1 } }])
  })
  it('after locking, every answer is frozen, yours is marked, and you see how many are in', () => {
    renderScreen('fff-locked')
    expect(screen.getByTestId('answer-1')).toHaveTextContent('Locked in')
    expect(screen.getByTestId('answer-0')).toBeDisabled()
    expect(screen.getByText(/Waiting for the others… \(3\/4 in\)/)).toBeInTheDocument()
  })
  it('the reveal lists correct answers fastest first with the points each earned', () => {
    renderScreen('fff-reveal')
    const list = screen.getByRole('list', { name: 'Correct answers, fastest first' })
    expect(list.textContent).toMatch(/Bob.*\+100.*You.*\+75/)
  })
  it('says so when you were too late, and when nobody got it', () => {
    const { unmount } = renderScreen('fff-reveal-too-late')
    expect(screen.getByText(/did not answer in time/)).toBeInTheDocument()
    unmount()
    renderScreen('fff-nobody')
    expect(screen.getByText(/Nobody answered/)).toBeInTheDocument()
  })
})

describe('Survival', () => {
  it('shows the streak and the live board, and give up is one click', async () => {
    renderScreen('surv-playing')
    expect(screen.getByTestId('streak')).toHaveTextContent('6')
    expect(screen.getByRole('heading', { name: 'Live board' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Give up' }))
    expect(sent).toEqual([{ t: 'FORFEIT' }])
  })
  it('a finished run explains why, and never calls a give-up a record', async () => {
    renderScreen('surv-gave-up')
    expect(await screen.findByText('You gave up.')).toBeInTheDocument()
    expect(screen.getByText(/never counts as a personal best/)).toBeInTheDocument()
  })
  it('a run that beat the previous best is celebrated', async () => {
    renderScreen('surv-over-timeout')
    expect(await screen.findByText(/New personal best/)).toBeInTheDocument()       // streak 6 against a best of 4
  })
  it('a spectator only sees the board', () => {
    renderScreen('surv-spectating')
    expect(screen.getByText(/You are watching/)).toBeInTheDocument()
    expect(screen.queryByTestId('streak')).toBeNull()
  })
})

describe('Results', () => {
  it('names the winner, shows everyone, and only the host can start another game', async () => {
    renderScreen('results-win')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Bob wins!')
    expect(screen.getByRole('table', { name: 'Final standings' }).querySelectorAll('tbody tr')).toHaveLength(4)
    expect(screen.getByText(/went AFK/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Play again' }))
    expect(sent).toEqual([{ t: 'REMATCH' }])
  })
  it('a player sees a waiting message instead of the button', () => {
    renderScreen('results-player-view')
    expect(screen.queryByRole('button', { name: 'Play again' })).toBeNull()
    expect(screen.getByText('Waiting for the host to start another game.')).toBeInTheDocument()
  })
  it('handles a tie, an empty result and Survival', () => {
    const a = renderScreen('results-tie'); expect(screen.getByText(/Tied on points/)).toBeInTheDocument(); a.unmount()
    const b = renderScreen('results-empty'); expect(screen.getByText(/Everyone left/)).toBeInTheDocument(); b.unmount()
    renderScreen('results-survival'); expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Runs finished')
    expect(screen.getByText(/gave up/)).toBeInTheDocument()
  })
})
