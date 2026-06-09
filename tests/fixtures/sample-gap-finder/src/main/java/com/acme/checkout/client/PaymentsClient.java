package com.acme.checkout.client;

import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

@Component
public class PaymentsClient {

    private final RestTemplate restTemplate;
    private final String baseUrl;

    public PaymentsClient(RestTemplate restTemplate, String baseUrl) {
        this.restTemplate = restTemplate;
        this.baseUrl = baseUrl;
    }

    // PLANTED GAP: a remote charge call guarded by a circuit breaker but with NO timeout.
    // The breaker opens on failures, but a hung connection still ties up the caller indefinitely.
    @CircuitBreaker(name = "payments", fallbackMethod = "chargeFallback")
    public Receipt charge(String orderId, long amountCents) {
        return restTemplate.postForObject(baseUrl + "/charge", new Charge(orderId, amountCents), Receipt.class);
    }

    // PLANTED NOVEL GAP (out-of-taxonomy): the breaker fallback converts an infrastructure
    // failure into a normal business "declined" receipt — callers and metrics can't tell an
    // outage from a real decline. No taxonomy category covers this; it exercises the
    // open-discovery channel (category=novel).
    private Receipt chargeFallback(String orderId, long amountCents, Throwable t) {
        return Receipt.declined(orderId);
    }
}
