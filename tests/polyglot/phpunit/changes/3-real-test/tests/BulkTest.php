<?php

declare(strict_types=1);

namespace Shop\Tests;

use PHPUnit\Framework\TestCase;
use Shop\Pricing;

final class BulkTest extends TestCase
{
    public function testLeavesASmallOrderAtFullPrice(): void
    {
        $this->assertSame(500, Pricing::total(250, 2));
    }

    public function testGivesTenItemsTenPercentOff(): void
    {
        $this->assertSame(9000, Pricing::total(1000, 10));
    }
}
