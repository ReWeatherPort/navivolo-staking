module volo_yield_optimizer::auto_stake {
    use sui::tx_context::{Self, TxContext};
    use sui::coin::{Self, Coin};
    use sui::transfer;
    use sui::object::{Self, UID};
    use navi_protocol::lending;
    use navi_protocol::pool;

    struct StakeRecord has key, store {
        id: UID,
        pool_id: address,
        amount: u64,
        timestamp: u64,
    }

    public entry fun stake_sui(
        sui: Coin<SUI>,
        amount: u64,
        pool_id: address,
        ctx: &mut TxContext
    ) {
        let stake_amount = coin::split(&mut sui, amount, ctx);
        pool::stake(stake_amount, pool_id, ctx);
        let record = StakeRecord {
            id: object::new(ctx),
            pool_id,
            amount,
            timestamp: tx_context::epoch(ctx),
        };
        transfer::public_transfer(record, tx_context::sender(ctx));
        transfer::public_transfer(sui, tx_context::sender(ctx));
    }

    public entry fun compound_vsui(
        vsui: Coin<VSUI>,
        amount: u64,
        lend_market: address,
        ctx: &mut TxContext
    ) {
        let reward_amount = coin::split(&mut vsui, amount, ctx);
        lending::supply(reward_amount, lend_market, ctx);
        transfer::public_transfer(vsui, tx_context::sender(ctx));
    }

    public entry fun auto_compound(
        wallet: address,
        pool_id: address,
        lend_market: address,
        ctx: &mut TxContext
    ) {
        let rewards = pool::get_rewards(wallet, pool_id, ctx);
        if (rewards > 0) {
            let vsui = pool::claim_rewards(wallet, pool_id, rewards, ctx);
            lending::supply(vsui, lend_market, ctx);
        }
    }
}