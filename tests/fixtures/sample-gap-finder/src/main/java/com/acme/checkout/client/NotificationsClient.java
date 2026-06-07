package com.acme.checkout.client;

import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

@Component
public class NotificationsClient {

    private final RestTemplate restTemplate;
    private final String baseUrl;

    public NotificationsClient(RestTemplate restTemplate, String baseUrl) {
        this.restTemplate = restTemplate;
        this.baseUrl = baseUrl;
    }

    // UNGUARDED: a synchronous remote call with no resilience wrapper at all, and no config for
    // it either. The unguarded-critical-dependency probe must confirm this gap.
    public void notifyShipped(String orderId) {
        restTemplate.postForObject(baseUrl + "/notify", new Event(orderId), Void.class);
    }
}
