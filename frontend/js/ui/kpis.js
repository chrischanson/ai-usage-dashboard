import { formatNum } from '../format.js';
import { setCard } from './skeleton.js';

export function renderOverview(data) {
    setCard('total-sessions', formatNum(data.sessions));
    setCard('total-messages', formatNum(data.messages));
    setCard('input-tokens', formatNum(data.input_tokens));
    setCard('output-tokens', formatNum(data.output_tokens));
    setCard('cache-reads', formatNum(data.cache_read));
}
