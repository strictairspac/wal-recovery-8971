import {DRILL_STATUSES,PURGE_STATUSES} from '../../constants/enums.js';
import {esc} from '../../utils/html.js';
export const badge=(status,labels=DRILL_STATUSES)=>`<span class="badge ${esc(status)}">${esc(labels[status]||status)}</span>`;
export const purgeBadge=(status)=>badge(status,PURGE_STATUSES);
