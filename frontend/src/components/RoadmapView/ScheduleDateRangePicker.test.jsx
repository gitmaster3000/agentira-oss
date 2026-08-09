import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { ScheduleDateRangePicker } from './ScheduleDateRangePicker';

const picker = vi.hoisted(() => ({ props: null }));

vi.mock('react-datepicker', () => ({
    default: (props) => {
        picker.props = props;
        return (
            <button
                type="button"
                onClick={() => props.onChange([
                    new Date('2026-09-10T00:00:00'),
                    new Date('2026-09-20T00:00:00'),
                ])}
            >
                Pick React range
            </button>
        );
    },
}));

describe('ScheduleDateRangePicker', () => {
    it('configures react-datepicker for ranges and forwards the selected window', () => {
        const onChange = vi.fn();
        render(
            <ScheduleDateRangePicker
                startDate={null}
                endDate={null}
                onChange={onChange}
            />,
        );

        expect(picker.props.selectsRange).toBe(true);
        expect(picker.props.showMonthDropdown).toBe(true);
        expect(picker.props.showYearDropdown).toBe(true);

        fireEvent.click(screen.getByRole('button', { name: 'Pick React range' }));
        expect(onChange).toHaveBeenCalledWith([
            new Date('2026-09-10T00:00:00'),
            new Date('2026-09-20T00:00:00'),
        ]);
    });

    it('clears an active range back to the full schedule', () => {
        const onChange = vi.fn();
        render(
            <ScheduleDateRangePicker
                startDate={new Date('2026-09-10T00:00:00')}
                endDate={new Date('2026-09-20T00:00:00')}
                onChange={onChange}
            />,
        );

        fireEvent.click(screen.getByRole('button', { name: 'Clear schedule date range' }));
        expect(onChange).toHaveBeenCalledWith([null, null]);
    });
});
