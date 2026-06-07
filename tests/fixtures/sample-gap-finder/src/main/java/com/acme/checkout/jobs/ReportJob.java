package com.acme.checkout.jobs;

import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
public class ReportJob {

    // A recurring job the engine has no ScheduledJob collector for — so no Flow/runbook covers it.
    // The undocumented-job confirmation probe fires the `scheduled` signature at the pointer.
    @Scheduled(cron = "0 0 2 * * *")
    public void emitDailyReconciliation() {
        // nightly reconciliation work
    }
}
