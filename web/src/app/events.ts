/** Plain-English lines for the "what just happened" feed and the screen-reader announcements. */
export function describeEvent(kind: string, p: Record<string, unknown>, name: (id: number) => string): string | null {
  const who = typeof p.player === 'number' ? name(p.player) : ''
  const n = (v: unknown) => (typeof v === 'number' ? Math.abs(v) : 0)
  switch (kind) {
    case 'turn_start': return `${who}'s turn.`
    case 'turn_skipped': return `${who} is silenced and loses this turn.`
    case 'card_drawn': return `${who} draws ${String(p.card)}.`
    case 'wheel_result': return `The wheel lands on ${String(p.segment)} for ${who}.`
    case 'monkey_result': {
      const d = typeof p.delta === 'number' ? p.delta : null
      return `${who} picks the ${String(p.choice)}${d === null ? '' : d >= 0 ? ` and gains ${n(d)}` : ` and loses ${n(d)}`}.`
    }
    case 'scores_swapped': return `${name(p.a as number)} and ${name(p.b as number)} swap scores.`
    case 'steal': return `${name(p.to as number)} steals from ${name(p.from as number)}.`
    case 'law_set': return `${who} sets a new law.`
    case 'law_expired': return 'The law has expired.'
    case 'law_effect': return `A law takes effect on ${who}.`
    case 'mist_on': return 'The Mystic Mist descends. Scores are hidden.'
    case 'mist_off': return 'The Mist clears.'
    case 'golden_pass_used': return `${who} burns their Golden Pass.`
    case 'player_removed': case 'player_left': return `${name(p.player as number)} is out of the game.`
    case 'sudden_bamboozle': return 'Tie at the top! Sudden Bamboozle.'
    case 'streak_breaker': return `Streak Breaker: ${who} draws a Wango card instead.`
    case 'chain_recoil': return 'The Double Wango chain recoils.'
    case 'round_end': return `Round ${String(p.round)} is over.`
    case 'game_over': return 'The game is over.'
    default: return null
  }
}
