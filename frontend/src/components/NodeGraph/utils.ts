import { STATUS_HEX } from '../../constants/statusColors';
import { COLOR_TEXT_SECONDARY } from '../../constants/styleColors';

/** Maps a node status string to a hex fill colour. */
export function nodeColor(status: string): string {
  return STATUS_HEX[status] ?? COLOR_TEXT_SECONDARY;
}
