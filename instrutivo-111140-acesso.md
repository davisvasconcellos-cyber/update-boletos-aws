# Acesso ao banco msf_cobranca e ao repositório msf-cobranca-api

Manutenção #111140. As senhas e os nomes de usuário são enviados à parte, por canal seguro.

## 1. Banco de dados (túnel SSH pelo bastion)

O banco não tem acesso público. O acesso é feito por um túnel SSH no servidor bastion, a partir de um IP liberado (o IP cadastrado de cada um ou a VPN do MSF).

| Item | Valor |
|---|---|
| Bastion | `34.204.24.206`, porta 22 |
| Usuário SSH | o seu usuário no bastion (Luiz: `luiz`; Davis: informado após o cadastro da nova chave) |
| Banco de homologação | `10.1.10.101:3306` |
| Banco de produção | informado após a aplicação em produção |
| Banco | `msf_cobranca` |

1. Abra o túnel e deixe o terminal aberto:

   ```bash
   ssh -N -L 3307:10.1.10.101:3306 <usuario_ssh>@34.204.24.206 -i <caminho da sua chave privada>
   ```

2. Em outro terminal ou na sua ferramenta (DBeaver, MySQL Workbench, etc.), conecte em `127.0.0.1`, porta `3307`:

   ```bash
   mysql -h 127.0.0.1 -P 3307 -u <usuario_mysql> -p msf_cobranca
   ```

3. Para validar o acesso:

   ```sql
   SHOW TABLES;
   SHOW EVENTS;
   SELECT COUNT(*) FROM vw_boletos_segunda_via_ativos;
   ```

## 2. Repositório (CodeCommit)

| Item | Valor |
|---|---|
| Repositório | `msf-cobranca-api` |
| URL SSH | `ssh://git-codecommit.us-east-1.amazonaws.com/v1/repos/msf-cobranca-api` |
| Usuário SSH | ID da chave SSH no IAM (Luiz: o mesmo dos outros repositórios; Davis: informado após o cadastro da chave) |

1. No `~/.ssh/config`:

   ```
   Host git-codecommit.*.amazonaws.com
     User <ID da chave SSH no IAM>
     IdentityFile <caminho da sua chave privada>
   ```

2. Clone:

   ```bash
   git clone ssh://git-codecommit.us-east-1.amazonaws.com/v1/repos/msf-cobranca-api
   ```

## Pontos de atenção

* Nunca envie a chave privada (arquivo sem `.pub`) nem a senha dela. Para cadastro, só o arquivo `.pub`.
* O usuário de banco de cada pessoa só funciona pelo túnel do bastion e só tem acesso ao `msf_cobranca`.
* O evento de limpeza roda todos os dias às 03:00 UTC (00:00 de Brasília). Ele foi criado pelo usuário administrativo: se for recriado com um usuário pessoal, passa a depender desse usuário.
* Use dados fictícios ou anonimizados em homologação.
