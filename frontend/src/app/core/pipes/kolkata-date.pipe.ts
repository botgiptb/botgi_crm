import { Pipe, PipeTransform } from '@angular/core';

@Pipe({
  name: 'kolkataDate',
  standalone: true,
})
export class KolkataDatePipe implements PipeTransform {
  private readonly formatter = new Intl.DateTimeFormat('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  });

  transform(value: string | Date | null | undefined): string {
    if (!value) {
      return '—';
    }
    const date = typeof value === 'string' ? new Date(value) : value;
    if (isNaN(date.getTime())) {
      return '—';
    }
    return this.formatter.format(date);
  }
}
