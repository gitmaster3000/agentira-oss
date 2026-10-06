import React, { useEffect, useState } from 'react';
import { api } from '../../api';
import { CheckCircle2, AlertCircle } from 'lucide-react';

// One plain-language line under the Definition of Done: who tested the task
// themselves end to end (with the proof to open), or that nobody has yet.
// `refreshKey` re-fetches when the task's files change.
export function TestedBy({ taskId, refreshKey }) {
    const [proof, setProof] = useState(null);

    useEffect(() => {
        let live = true;
        api.getTaskProof(taskId)
            .then((p) => { if (live) setProof(p); })
            .catch(() => { if (live) setProof(null); });
        return () => { live = false; };
    }, [taskId, refreshKey]);

    if (!proof) return null;

    if (proof.present) {
        return (
            <div className="flex items-center gap-2 text-xs text-text-secondary" data-testid="tested-by">
                <CheckCircle2 className="w-3.5 h-3.5 flex-shrink-0" style={{ color: '#2ecc71' }} />
                <span>
                    Tested by {proof.tested_by} —{' '}
                    <button
                        type="button"
                        className="underline hover:text-text-primary"
                        onClick={() => api.downloadAttachment(proof.attachment_id, proof.filename)
                            .catch((err) => alert('Failed to open proof: ' + err.message))}
                    >
                        see proof
                    </button>
                </span>
            </div>
        );
    }

    return (
        <div className="flex items-center gap-2 text-xs text-text-tertiary" data-testid="tested-by">
            <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
            <span>
                {proof.stale
                    ? 'Changed since it was last tested — needs fresh proof.'
                    : 'Not tested yet — no proof attached.'}
            </span>
        </div>
    );
}
