import { formatNum } from '../format.js';
import { setCard } from './skeleton.js';

export function renderOverview(data) {
    setCard('total-sessions', formatNum(data.sessions), 'Sessions');
    setCard('total-messages', formatNum(data.messages), 'Messages');
    setCard('input-tokens', formatNum(data.input_tokens), 'In');
    setCard('output-tokens', formatNum(data.output_tokens), 'Out');
    setCard('cache-reads', formatNum(data.cache_read));
}
