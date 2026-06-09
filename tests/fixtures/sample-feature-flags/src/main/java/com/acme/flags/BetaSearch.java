package com.acme.flags;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(prefix = "features", name = "beta-search", matchIfMissing = false)
public class BetaSearch {

    private final LdClient ldClient;

    public BetaSearch(LdClient ldClient) {
        this.ldClient = ldClient;
    }

    public boolean enabled(String user) {
        return ldClient.boolVariation("new-pricing", user, false);
    }
}
