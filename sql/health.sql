-- name: create_schema#
create table fitbit_token (
  id text not null unique primary key,
  access_token text not null,
  refresh_token text not null,
  expires_at float not null,
  enable_report boolean not null default false
);


create table withings_token (
  id int not null unique primary key,
  access_token text not null,
  refresh_token text not null,
  expires_at int not null,
  enable_report boolean not null default false
);


create table fitbit_token_gargling (
  fitbit_id text not null references fitbit_token(id),
  gargling_id smallint not null references gargling(id)
);


create table withings_token_gargling (
  withings_id int not null references withings_token(id),
  gargling_id smallint not null references gargling(id)
);


-- name: persist_token!
insert into
  /*{{ {"fitbit": "fitbit_token", "withings": "withings_token"}[service] }}*/
  (
    id,
    access_token,
    refresh_token,
    expires_at
  )
values
  (
    :id,
    :access_token,
    :refresh_token,
    :expires_at
  ) on conflict (id) do
update
set
  (access_token, refresh_token, expires_at) = (
    excluded.access_token,
    excluded.refresh_token,
    excluded.expires_at
  );


--name: toggle_report!
update
  /*{{ {"fitbit": "fitbit_token", "withings": "withings_token"}[service] }}*/
  as service_token
set
  enable_report = :enable_
from
  /*{{ {"fitbit": "fitbit_token_gargling", "withings": "withings_token_gargling"}[service] }}*/
  as service_token_gargling
where
  service_token.id = service_token_gargling.
  /*{{ {"fitbit": "fitbit_id", "withings": "withings_id"}[service] }}*/
  and service_token_gargling.gargling_id = :gargling_id;


-- name: match_ids!
delete from
  /*{{ {"fitbit": "fitbit_token_gargling", "withings": "withings_token_gargling"}[service] }}*/
where
  gargling_id = :gargling_id;


insert into
  /*{{ {"fitbit": "fitbit_token_gargling", "withings": "withings_token_gargling"}[service] }}*/
  (
    /*{{"fitbit_id" if service == "fitbit" else "withings_id" }}*/
,
    gargling_id
  )
values
  (:service_user_id, :gargling_id);


-- name: is_registered^
select
  service_token.enable_report
from
  /*{{ {"fitbit": "fitbit_token", "withings": "withings_token"}[service] }}*/
  as service_token
  inner join
  /*{{ {"fitbit": "fitbit_token_gargling", "withings": "withings_token_gargling"}[service] }}*/
  as service_token_gargling on service_token.id = service_token_gargling.
  /*{{ {"fitbit": "fitbit_id", "withings": "withings_id"}[service] }}*/
where
  service_token_gargling.gargling_id = :gargling_id;


-- name: tokens
select
  fitbit.id,
  fitbit.access_token,
  fitbit.refresh_token,
  fitbit.expires_at,
  gargling.first_name,
  'fitbit' as service
from
  fitbit_token as fitbit
  inner join fitbit_token_gargling on fitbit.id = fitbit_token_gargling.fitbit_id
  inner join gargling on fitbit_token_gargling.gargling_id = gargling.id
  /*{% if slack_nicks or only_report %}*/
where
  /*{% endif  %}*/
  /*{% set and = joiner(" and ") %}*/
  /*{% if slack_nicks %}*/
  /*{{ and() }}*/
  gargling.slack_nick = any(:slack_nicks)
  /*{% endif  %}*/
  /*{% if only_report %}*/
  /*{{ and() }}*/
  fitbit.enable_report
  /*{% endif  %}*/
union
all
select
  withings.id :: text,
  withings.access_token,
  withings.refresh_token,
  withings.expires_at :: float,
  gargling.first_name,
  'withings' as service
from
  withings_token as withings
  inner join withings_token_gargling on withings.id = withings_token_gargling.withings_id
  inner join gargling on withings_token_gargling.gargling_id = gargling.id
  /*{% if slack_nicks or only_report %}*/
where
  /*{% endif  %}*/
  /*{% set and = joiner(" and ") %}*/
  /*{% if slack_nicks %}*/
  /*{{ and() }}*/
  gargling.slack_nick = any(:slack_nicks)
  /*{% endif  %}*/
  /*{% if only_report %}*/
  /*{{ and() }}*/
  withings.enable_report
  /*{% endif  %}*/
;


-- name: all_ids_nicks
select
  id,
  slack_nick
from
  gargling;
