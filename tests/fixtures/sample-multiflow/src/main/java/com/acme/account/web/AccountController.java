package com.acme.account.web;

import com.acme.account.repo.Account;
import com.acme.account.repo.AccountRepository;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/accounts")
public class AccountController {

    private final AccountRepository accountRepository;

    public AccountController(AccountRepository accountRepository) {
        this.accountRepository = accountRepository;
    }

    @PostMapping("/open")
    public AccountResponse openAccount(@RequestBody OpenRequest request) {
        Account account = accountRepository.save(new Account(request.getOwner()));
        return new AccountResponse(account.getId());
    }

    @PostMapping("/close")
    public void closeAccount(@RequestBody CloseRequest request) {
        Account account = accountRepository.getOne(request.getId());
        account.close();
        accountRepository.save(account);
    }
}
