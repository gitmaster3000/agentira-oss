import React, { forwardRef } from 'react';
import DatePicker from 'react-datepicker';
import { CalendarRange, X } from 'lucide-react';
import 'react-datepicker/dist/react-datepicker.css';
import './schedule-datepicker.css';

const DateRangeTrigger = forwardRef(function DateRangeTrigger(
    { value, onClick },
    ref,
) {
    return (
        <button
            ref={ref}
            type="button"
            onClick={onClick}
            className="input w-auto min-w-[220px] py-2 px-3 flex items-center gap-2 text-left"
            aria-label="Schedule date range"
        >
            <CalendarRange className="w-4 h-4 text-text-tertiary flex-shrink-0" />
            <span className={value ? 'text-text-primary' : 'text-text-tertiary'}>
                {value || 'All scheduled dates'}
            </span>
        </button>
    );
});

/**
 * One controlled React date-range picker shared by every Schedule mode.
 * Keeping it above the mode switch means calendar/timeline changes never
 * reset the user's planning window.
 */
export function ScheduleDateRangePicker({ startDate, endDate, onChange }) {
    return (
        <div className="flex items-center gap-1.5">
            <DatePicker
                selectsRange
                startDate={startDate}
                endDate={endDate}
                onChange={onChange}
                customInput={<DateRangeTrigger />}
                dateFormat="MMM d, yyyy"
                rangeSeparator=" — "
                monthsShown={1}
                showMonthDropdown
                showYearDropdown
                dropdownMode="select"
                calendarClassName="schedule-datepicker"
                popperClassName="schedule-datepicker-popper"
                popperPlacement="bottom-end"
            />
            {startDate && (
                <button
                    type="button"
                    onClick={() => onChange([null, null])}
                    className="p-1.5 rounded text-text-tertiary hover:text-text-secondary hover:bg-bg-hover transition-colors"
                    aria-label="Clear schedule date range"
                    title="Show all scheduled dates"
                >
                    <X className="w-4 h-4" />
                </button>
            )}
        </div>
    );
}
